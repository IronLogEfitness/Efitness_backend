"""Conversation persistence: storage, the sliding-window read path, the
summarisation *boundary* maths, import, and the published-reference lookup.

This module is deliberately LLM-agnostic — it never imports Gemini. The actual
summary text is produced by ``app.chat.gemini`` and handed back here via
``apply_summary``; ``pending_summarization`` only decides *what* to fold and
*when*. That keeps the persistence layer testable and avoids a cycle with the
chat feature.

Every query is scoped by ``user_id`` (the ObjectId from the verified JWT), so a
user can only ever read or write their own conversations and messages.
"""
import re

from bson import ObjectId

from app.conversations.models import (
    CONVERSATIONS_COLLECTION,
    MESSAGES_COLLECTION,
    ROLE_ASSISTANT,
    ROLE_USER,
    SOURCE_CHAT,
    SOURCE_GEMINI_IMPORT,
    ConversationDocument,
    MessageDocument,
)
from app.conversations.schemas import (
    ConversationDetailResponse,
    ConversationImportRequest,
    ConversationResponse,
    ConversationUpdate,
    MessageResponse,
)
from app.helpers.dates import now_utc
from app.helpers.exceptions import BadRequestError, NotFoundError
from app.helpers.filters import Pagination
from app.helpers.objectid import parse_object_id

# Safety cap on how many raw messages we ever load into a prompt. The
# sliding-window summarisation keeps the unsummarised tail near the token
# threshold, so this is only a backstop against pathological cases.
MAX_ACTIVE_MESSAGES = 60
# Token budget for injected published-reference material (Feature 3).
REFERENCE_TOKEN_BUDGET = 1500

_USER_MARKERS = {"user", "you", "me", "prompt"}
_ASSISTANT_MARKERS = {"gemini", "bard", "assistant", "model", "ai", "response"}
_MARKER_RE = re.compile(
    r"^\s*(user|you|me|prompt|gemini|bard|assistant|model|ai|response)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_SEPARATOR_RE = re.compile(r"(?m)^\s*-{3,}\s*$")


# ── Token estimate ──
def estimate_tokens(text: str) -> int:
    """Rough token count (~4 chars/token), computed once at write time so reads
    never recount. Exact counts for assistant turns are captured from Gemini's
    usage metadata instead; this estimate covers user/imported messages and the
    window-size threshold decisions, where approximate is good enough."""
    return max(1, (len(text) + 3) // 4)


# ── Serialisers ──
def _to_conversation_response(doc: dict) -> ConversationResponse:
    return ConversationResponse(
        id=str(doc["_id"]),
        title=doc.get("title"),
        source=doc.get("source", SOURCE_CHAT),
        is_published=doc.get("is_published", False),
        label=doc.get("label"),
        message_count=doc.get("message_count", 0),
        has_summary=bool(doc.get("summary")),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _to_message_response(doc: dict) -> MessageResponse:
    return MessageResponse(
        id=str(doc["_id"]),
        seq=doc["seq"],
        role=doc["role"],
        content=doc["content"],
        token_count=doc["token_count"],
        created_at=doc["created_at"],
    )


def derive_title(text: str, fallback: str = "New conversation") -> str:
    text = (text or "").strip().replace("\n", " ")
    if not text:
        return fallback
    return f"{text[:60]}…" if len(text) > 60 else text


# ── Core persistence (used by the chat orchestration) ──
async def create_conversation(
    db, user_id: ObjectId, source: str = SOURCE_CHAT, title: str | None = None
) -> dict:
    """Insert a new (empty) conversation and return the stored document."""
    doc = ConversationDocument(user_id=user_id, source=source, title=title).model_dump()
    result = await db[CONVERSATIONS_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def require_conversation(db, user_id: ObjectId, conversation_id) -> dict:
    """Fetch a conversation owned by this user, or raise 404/400."""
    oid = (
        conversation_id
        if isinstance(conversation_id, ObjectId)
        else parse_object_id(conversation_id, "conversation id")
    )
    doc = await db[CONVERSATIONS_COLLECTION].find_one({"_id": oid, "user_id": user_id})
    if not doc:
        raise NotFoundError("Conversation not found")
    return doc


async def append_message(
    db, conversation: dict, role: str, content: str, token_count: int | None = None
) -> dict:
    """Append one message, assigning the next ``seq`` via an atomic counter on
    the conversation. ``token_count`` is supplied for assistant turns (exact,
    from Gemini) and estimated otherwise."""
    if token_count is None:
        token_count = estimate_tokens(content)

    # Atomically claim the next seq and bump updated_at. return_document=True
    # returns the post-update doc (matches the sessions service convention).
    updated = await db[CONVERSATIONS_COLLECTION].find_one_and_update(
        {"_id": conversation["_id"], "user_id": conversation["user_id"]},
        {"$inc": {"message_count": 1}, "$set": {"updated_at": now_utc()}},
        return_document=True,
    )
    if updated is None:
        raise NotFoundError("Conversation not found")

    doc = MessageDocument(
        conversation_id=conversation["_id"],
        user_id=conversation["user_id"],
        seq=updated["message_count"],
        role=role,
        content=content,
        token_count=token_count,
    ).model_dump()
    result = await db[MESSAGES_COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def load_recent_messages(db, conversation: dict) -> list[dict]:
    """The active raw window: messages after the summarised boundary, oldest
    first. Bounded by MAX_ACTIVE_MESSAGES (most recent kept if ever exceeded)."""
    boundary = conversation.get("summarized_through_seq", 0)
    docs = await (
        db[MESSAGES_COLLECTION]
        .find(
            {
                "conversation_id": conversation["_id"],
                "user_id": conversation["user_id"],
                "seq": {"$gt": boundary},
            }
        )
        .sort("seq", -1)
        .limit(MAX_ACTIVE_MESSAGES)
        .to_list(MAX_ACTIVE_MESSAGES)
    )
    docs.reverse()
    return docs


# ── Sliding-window summarisation (boundary maths only; LLM call lives in chat) ──
async def pending_summarization(
    db, conversation_id: ObjectId, user_id: ObjectId, token_threshold: int, keep_last: int
):
    """Decide whether older turns should be folded into the summary.

    Returns ``(conversation, overflow_messages, boundary_seq, previous_summary)``
    when the unsummarised window has more than ``keep_last`` messages *and* its
    tokens (plus the existing summary) exceed ``token_threshold``; otherwise
    ``None``. ``overflow_messages`` is everything except the last ``keep_last``.
    """
    conv = await db[CONVERSATIONS_COLLECTION].find_one(
        {"_id": conversation_id, "user_id": user_id}
    )
    if not conv:
        return None

    boundary = conv.get("summarized_through_seq", 0)
    unsummarized = await (
        db[MESSAGES_COLLECTION]
        .find(
            {"conversation_id": conversation_id, "user_id": user_id, "seq": {"$gt": boundary}}
        )
        .sort("seq", 1)
        .to_list(length=500)
    )
    if len(unsummarized) <= keep_last:
        return None

    total_tokens = conv.get("summary_token_count", 0) + sum(
        m["token_count"] for m in unsummarized
    )
    if total_tokens <= token_threshold:
        return None

    overflow = unsummarized[:-keep_last]  # keep the last `keep_last` raw
    boundary_seq = overflow[-1]["seq"]
    return conv, overflow, boundary_seq, conv.get("summary")


async def apply_summary(
    db, conversation_id: ObjectId, user_id: ObjectId, summary: str, boundary_seq: int
) -> None:
    """Store a freshly computed summary and advance the summarised boundary. The
    folded messages stay in the collection — only what we *load* changes."""
    await db[CONVERSATIONS_COLLECTION].update_one(
        {"_id": conversation_id, "user_id": user_id},
        {
            "$set": {
                "summary": summary,
                "summary_token_count": estimate_tokens(summary),
                "summarized_through_seq": boundary_seq,
                "updated_at": now_utc(),
            }
        },
    )


# ── Published reference material (Feature 3) ──
async def build_reference_block(
    db, user_id: ObjectId, labels: list[str] | None, exclude_id: ObjectId | None = None
) -> str:
    """Assemble a context block from this user's *own* published conversations
    whose label matches one of ``labels``. Scoped to ``user_id`` (per-user, no
    cross-tenant exposure). Capped to REFERENCE_TOKEN_BUDGET tokens; prefers a
    conversation's summary, falling back to its raw messages."""
    if not labels:
        return ""

    query: dict = {"user_id": user_id, "is_published": True, "label": {"$in": labels}}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}

    convs = await (
        db[CONVERSATIONS_COLLECTION].find(query).sort("updated_at", -1).to_list(length=10)
    )
    if not convs:
        return ""

    blocks: list[str] = []
    budget = REFERENCE_TOKEN_BUDGET
    for conv in convs:
        if conv.get("summary"):
            snippet = conv["summary"]
        else:
            msgs = await (
                db[MESSAGES_COLLECTION]
                .find({"conversation_id": conv["_id"], "user_id": user_id})
                .sort("seq", 1)
                .to_list(length=50)
            )
            snippet = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)

        max_chars = budget * 4  # rough char budget for the remaining token budget
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars] + "…"

        title = conv.get("title") or "Reference"
        blocks.append(f"[{conv.get('label')}] {title}:\n{snippet}")

        budget -= estimate_tokens(snippet)
        if budget <= 0:
            break

    return "\n\n".join(blocks)


# ── Import (Feature 2) ──
def _normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r in _USER_MARKERS:
        return ROLE_USER
    if r in _ASSISTANT_MARKERS:
        return ROLE_ASSISTANT
    raise BadRequestError(f"Unknown message role: {role!r}")


def _parse_raw_text(raw_text: str) -> list[tuple[str, str]]:
    """Best-effort parse of a copy-pasted conversation into (role, content) turns.

    Precedence:
      1. lines starting with a role marker ("User:" / "Gemini:" / ...),
      2. else turns separated by a line of only dashes ("---"), alternating
         user/assistant starting with the user (you prompt first),
      3. else reject — we won't silently mangle an unsegmentable blob.
    """
    text = raw_text.strip()
    if not text:
        raise BadRequestError("raw_text is empty.")

    lines = text.splitlines()
    if any(_MARKER_RE.match(ln) for ln in lines):
        messages: list[tuple[str, str]] = []
        role: str | None = None
        buf: list[str] = []
        for ln in lines:
            m = _MARKER_RE.match(ln)
            if m:
                if role is not None:
                    content = "\n".join(buf).strip()
                    if content:
                        messages.append((role, content))
                role = _normalize_role(m.group(1))
                buf = [m.group(2)]
            else:
                if role is None:
                    role = ROLE_USER  # any preamble before the first marker is the user's
                buf.append(ln)
        if role is not None:
            content = "\n".join(buf).strip()
            if content:
                messages.append((role, content))
        if messages:
            return messages

    blocks = [b.strip() for b in _SEPARATOR_RE.split(text) if b.strip()]
    if len(blocks) > 1:
        return [
            (ROLE_USER if i % 2 == 0 else ROLE_ASSISTANT, block)
            for i, block in enumerate(blocks)
        ]

    raise BadRequestError(
        "Could not parse raw_text into turns. Prefix each turn with 'User:' / "
        "'Gemini:', or separate turns with a line containing only '---' (your "
        "prompt first)."
    )


async def import_conversation(
    db, user_id: ObjectId, body: ConversationImportRequest
) -> ConversationResponse:
    """Normalise a Gemini export into the internal message schema and store it as
    a new conversation flagged ``source="gemini_import"``."""
    if body.messages:
        pairs = [
            (_normalize_role(m.role), m.content.strip())
            for m in body.messages
            if m.content and m.content.strip()
        ]
    else:
        pairs = _parse_raw_text(body.raw_text or "")

    if not pairs:
        raise BadRequestError("No non-empty messages to import.")

    first_user = next((c for r, c in pairs if r == ROLE_USER), pairs[0][1])
    title = body.title or derive_title(first_user, "Imported conversation")

    conv = await create_conversation(
        db, user_id, source=SOURCE_GEMINI_IMPORT, title=title
    )

    now = now_utc()
    docs = [
        MessageDocument(
            conversation_id=conv["_id"],
            user_id=user_id,
            seq=i,
            role=role,
            content=content,
            token_count=estimate_tokens(content),
            created_at=now,
        ).model_dump()
        for i, (role, content) in enumerate(pairs, start=1)
    ]
    await db[MESSAGES_COLLECTION].insert_many(docs)

    # Advance the conversation's counter so future chat turns continue the seq.
    await db[CONVERSATIONS_COLLECTION].update_one(
        {"_id": conv["_id"], "user_id": user_id},
        {"$set": {"message_count": len(docs), "updated_at": now}},
    )
    conv["message_count"] = len(docs)
    return _to_conversation_response(conv)


# ── Router-facing read/update ──
async def list_conversations(
    db,
    user_id: ObjectId,
    page: Pagination,
    source: str | None = None,
    is_published: bool | None = None,
) -> list[ConversationResponse]:
    query: dict = {"user_id": user_id}
    if source:
        query["source"] = source
    if is_published is not None:
        query["is_published"] = is_published

    docs = await (
        db[CONVERSATIONS_COLLECTION]
        .find(query)
        .sort("updated_at", -1)
        .skip(page.skip)
        .limit(page.limit)
        .to_list(length=page.limit)
    )
    return [_to_conversation_response(d) for d in docs]


async def get_conversation_detail(
    db, user_id: ObjectId, conversation_id: str, page: Pagination
) -> ConversationDetailResponse:
    conv = await require_conversation(db, user_id, conversation_id)
    msgs = await (
        db[MESSAGES_COLLECTION]
        .find({"conversation_id": conv["_id"], "user_id": user_id})
        .sort("seq", 1)
        .skip(page.skip)
        .limit(page.limit)
        .to_list(length=page.limit)
    )
    base = _to_conversation_response(conv).model_dump()
    return ConversationDetailResponse(
        **base,
        summary=conv.get("summary"),
        messages=[_to_message_response(m) for m in msgs],
    )


async def update_conversation(
    db, user_id: ObjectId, conversation_id: str, body: ConversationUpdate
) -> ConversationResponse:
    oid = parse_object_id(conversation_id, "conversation id")

    update: dict = {}
    if body.title is not None:
        update["title"] = body.title
    if body.is_published is not None:
        update["is_published"] = body.is_published
    if body.label is not None:
        update["label"] = body.label
    if not update:
        raise BadRequestError("Nothing to update")
    update["updated_at"] = now_utc()

    doc = await db[CONVERSATIONS_COLLECTION].find_one_and_update(
        {"_id": oid, "user_id": user_id},
        {"$set": update},
        return_document=True,
    )
    if not doc:
        raise NotFoundError("Conversation not found")
    return _to_conversation_response(doc)
