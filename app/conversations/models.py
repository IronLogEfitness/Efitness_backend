"""Persistence models for the `conversations` and `messages` collections.

A conversation owns an ordered list of messages, stored in a *separate*
collection so we can cheaply load just the most recent turns (an embedded array
would mean rewriting the whole document on every append and risks the 16 MB
document cap). The conversation document also carries the rolling `summary` of
older turns and the publish/label flags used for reference injection.

Ordering: each message takes the conversation's next `seq` (a monotonic counter
incremented atomically on the conversation — see `service.append_message`). This
gives a deterministic order and a clean summarisation boundary
(`summarized_through_seq`) without relying on timestamp ties.
"""
from datetime import datetime

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.helpers.dates import now_utc

CONVERSATIONS_COLLECTION = "conversations"
MESSAGES_COLLECTION = "messages"

# Provenance, stored on `conversations.source`.
SOURCE_CHAT = "chat"
SOURCE_GEMINI_IMPORT = "gemini_import"

# Canonical message roles. Mapped to Gemini's "user"/"model" at send time.
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class ConversationDocument(BaseModel):
    """Shape of a conversation document as stored in MongoDB."""

    # arbitrary_types_allowed lets us keep `user_id` as a real ObjectId, so
    # model_dump() produces a dict ready to hand straight to Motor.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: ObjectId
    title: str | None = None
    source: str = SOURCE_CHAT
    # Rolling summary of all messages with seq <= summarized_through_seq.
    summary: str | None = None
    summary_token_count: int = 0
    # Monotonic per-conversation counter; each new message takes the next value.
    message_count: int = 0
    summarized_through_seq: int = 0
    # Feature 3: published reference material.
    is_published: bool = False
    label: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class MessageDocument(BaseModel):
    """Shape of a single message document as stored in MongoDB."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    conversation_id: ObjectId
    user_id: ObjectId  # denormalised owner: direct scoping + defence in depth
    seq: int
    role: str  # ROLE_USER | ROLE_ASSISTANT
    content: str
    token_count: int  # computed at write time so reads never recount
    created_at: datetime = Field(default_factory=now_utc)


async def ensure_indexes(db) -> None:
    """Create the indexes the chat-memory queries rely on. Idempotent — safe to
    call on every startup. (No other collection in the app declares indexes yet;
    these back the per-conversation message reads and the published lookup.)"""
    await db[MESSAGES_COLLECTION].create_index([("conversation_id", 1), ("seq", 1)])
    await db[CONVERSATIONS_COLLECTION].create_index([("user_id", 1), ("updated_at", -1)])
    await db[CONVERSATIONS_COLLECTION].create_index(
        [("user_id", 1), ("is_published", 1), ("label", 1)]
    )
