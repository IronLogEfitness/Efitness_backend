"""Persistence models for the agentic coach.

Two collections, both scoped by ``user_id`` (the ObjectId from the verified JWT):

  - ``coach_actions`` — one document per model-proposed write. It is the bridge
    between ``POST /chat`` (which inserts ``pending`` proposals) and
    ``POST /chat/confirm`` (which transitions them to ``executed`` / ``rejected`` /
    ``failed``). The ``(conversation_id, action_id)`` unique index is what makes
    confirm **idempotent**: re-confirming an already-``executed`` action is a no-op
    that returns the stored ``created_id`` instead of writing again.

  - ``coach_cache`` — memoised recap / briefing payloads keyed by ``(user_id,
    key)`` so re-opening the app re-serves the cached result and spends zero Gemini
    quota (Feature 8/9). ``key`` encodes the period, e.g. ``"recap:2026-W24"`` or
    ``"briefing:2026-06-13"``.
"""
from datetime import datetime
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.helpers.dates import now_utc

COACH_ACTIONS_COLLECTION = "coach_actions"
COACH_CACHE_COLLECTION = "coach_cache"

# coach_actions.status lifecycle.
STATUS_PENDING = "pending"
STATUS_EXECUTING = "executing"  # transient: claimed for execution (idempotency guard)
STATUS_EXECUTED = "executed"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"


class CoachActionDocument(BaseModel):
    """Shape of a proposed-action document as stored in MongoDB."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    conversation_id: ObjectId
    user_id: ObjectId  # denormalised owner: direct scoping + defence in depth
    action_id: str     # stable uuid4 minted at propose time
    type: str          # the write tool name, e.g. "log_sets"
    args: dict[str, Any]
    summary: str
    status: str = STATUS_PENDING
    created_id: str | None = None  # id of the row this action created, once executed
    detail: str | None = None      # failure / clarification message
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class CoachCacheDocument(BaseModel):
    """Shape of a cached recap / briefing payload as stored in MongoDB."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: ObjectId
    key: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=now_utc)


async def ensure_indexes(db) -> None:
    """Create the indexes the coach queries rely on. Idempotent — safe to call on
    every startup (alongside the conversations indexes)."""
    # Unique per conversation+action so confirm is idempotent and lookups are O(1).
    await db[COACH_ACTIONS_COLLECTION].create_index(
        [("conversation_id", 1), ("action_id", 1)], unique=True
    )
    await db[COACH_ACTIONS_COLLECTION].create_index([("user_id", 1), ("status", 1)])
    # One cached payload per (user, period key).
    await db[COACH_CACHE_COLLECTION].create_index(
        [("user_id", 1), ("key", 1)], unique=True
    )
