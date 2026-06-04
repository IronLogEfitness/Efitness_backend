"""AI coach orchestration.

Per turn this: resolves (or creates) the persistent conversation, assembles the
context — last-30-days training data + published references + rolling summary +
the recent raw turns — calls Gemini, saves both turns, and folds older turns into
the summary once the active window crosses the token threshold.

Persistence and the summarisation boundary maths live in ``app.conversations``;
the Gemini calls live in ``app.chat.gemini``. This module only wires them
together, so the data-access layer stays free of FastAPI and the LLM.

Security: every database read here is scoped to ``user["_id"]``, which comes
from the verified JWT (see ``app.auth.dependencies.get_current_user``) — never
from the request body. The model only ever sees the logged-in user's own data.
"""
import logging
from datetime import timedelta

from app.chat import gemini
from app.chat.schemas import ChatRequest
from app.config import settings
from app.conversations import service as conversations
from app.conversations.models import ROLE_ASSISTANT, ROLE_USER
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.helpers.exceptions import AppError
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION

logger = logging.getLogger(__name__)

CONTEXT_DAYS = 30


async def _build_training_block(db, user: dict) -> str:
    """A bullet list of the user's last 30 days of sessions, with exercise names.

    Scoped to ``user["_id"]`` so it can only read this user's own data.
    """
    user_id = user["_id"]
    since = now_utc() - timedelta(days=CONTEXT_DAYS)

    sessions = await db[SESSIONS_COLLECTION].find(
        {"user_id": user_id, "date": {"$gte": since}}
    ).sort("date", -1).limit(20).to_list(20)

    summaries = []
    for s in sessions:
        # Re-assert ownership on the exercise lookup (defence in depth).
        ex = await db[EXERCISES_COLLECTION].find_one(
            {"_id": s["exercise_id"], "user_id": user_id}
        )
        ex_name = ex["name"] if ex else "Unknown"
        muscle = ex["muscle"] if ex else "unknown"
        sets_text = ", ".join(
            f"{st['weight_kg']}kg×{st['reps']}" for st in s["sets"]
        )
        summaries.append(
            f"- {s['date'].strftime('%d %b')}: {ex_name} ({muscle}) | {sets_text}"
        )

    return "\n".join(summaries) if summaries else "No sessions logged yet."


def _build_system_prompt(
    user_name: str, training_block: str, reference_block: str, summary: str | None
) -> str:
    """Coach persona + the live training data, plus two clearly separated,
    optional context blocks: curated published references, and the condensed
    summary of earlier turns in this conversation."""
    sections = [
        "You are IronLog AI, a knowledgeable and motivating personal fitness coach.",
        "You have access to the user's real training data from the last 30 days shown below.",
        "Use this data to give personalised, specific advice. Reference actual numbers from their sessions.",
        "Be concise, practical, and encouraging. Never be generic — always tie your answer to their data.",
        f"\nUSER: {user_name}",
        f"\nRECENT TRAINING DATA (last {CONTEXT_DAYS} days):\n{training_block}",
    ]

    if reference_block:
        sections.append(
            "\nPUBLISHED REFERENCE MATERIAL (curated by the user as authoritative "
            "background — not part of the live conversation):\n"
            f"{reference_block}"
        )

    if summary:
        sections.append(
            "\nCONVERSATION SUMMARY (earlier messages in this conversation, condensed):\n"
            f"{summary}"
        )

    sections.append(
        "\nRules:\n"
        "- Keep replies under 150 words unless a detailed explanation is truly needed.\n"
        "- When recommending weight increases, suggest specific numbers based on their data.\n"
        "- If they have no data yet, encourage them to log their first session.\n"
        "- Never make up data — only use what is shown above."
    )
    return "\n".join(sections)


async def _maybe_summarize(db, conversation_id, user_id) -> None:
    """Fold older turns into the rolling summary once the active window exceeds
    the token threshold. Best-effort: a summarisation failure is logged but never
    breaks the chat reply (the raw messages are still safely stored)."""
    try:
        pending = await conversations.pending_summarization(
            db,
            conversation_id,
            user_id,
            settings.CHAT_SUMMARY_TOKEN_THRESHOLD,
            settings.CHAT_HISTORY_LIMIT,
        )
        if not pending:
            return
        _conv, overflow, boundary_seq, previous_summary = pending
        new_summary = await gemini.summarize(previous_summary, overflow)
        await conversations.apply_summary(
            db, conversation_id, user_id, new_summary, boundary_seq
        )
    except AppError as e:
        logger.warning("Summarisation skipped for %s: %s", conversation_id, e.detail)
    except Exception:  # never let memory maintenance break the user's reply
        logger.exception("Unexpected error summarising conversation %s", conversation_id)


async def chat(db, user: dict, body: ChatRequest) -> tuple[str, str]:
    """Run one chat turn. Returns ``(reply, conversation_id)``."""
    if not settings.GEMINI_API_KEY:
        # 500: a configuration problem, not a client error.
        raise AppError("GEMINI_API_KEY not configured")

    user_id = user["_id"]

    # 1. Resolve or create the conversation — the server owns history now.
    if body.conversation_id:
        conversation = await conversations.require_conversation(
            db, user_id, body.conversation_id
        )
    else:
        conversation = await conversations.create_conversation(
            db, user_id, title=conversations.derive_title(body.message)
        )

    # 2. Assemble context: training data + published refs + summary + recent turns.
    training_block = await _build_training_block(db, user)
    reference_block = await conversations.build_reference_block(
        db, user_id, body.reference_labels, exclude_id=conversation["_id"]
    )
    recent = await conversations.load_recent_messages(db, conversation)
    system_prompt = _build_system_prompt(
        user["name"], training_block, reference_block, conversation.get("summary")
    )

    # Gemini uses the roles "user" and "model" (not "assistant").
    contents = []
    for m in recent:
        role = "model" if m["role"] == ROLE_ASSISTANT else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": body.message}]})

    # 3. Call Gemini.
    reply, usage = await gemini.generate(system_prompt, contents)

    # 4. Persist both turns immediately. Store the exact assistant token count
    #    from Gemini's usage metadata when present; estimate the user's.
    await conversations.append_message(db, conversation, ROLE_USER, body.message)
    await conversations.append_message(
        db,
        conversation,
        ROLE_ASSISTANT,
        reply,
        token_count=usage.get("candidates_token_count"),
    )

    # 5. Compress older turns if we crossed the token threshold.
    await _maybe_summarize(db, conversation["_id"], user_id)

    return reply, str(conversation["_id"])
