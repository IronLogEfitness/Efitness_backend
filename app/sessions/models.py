"""Persistence model for the `sessions` collection."""
from datetime import datetime

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.helpers.dates import now_utc

COLLECTION = "sessions"


class SetDocument(BaseModel):
    set_number: int
    weight_kg: float
    reps: int


class SessionDocument(BaseModel):
    """Shape of a training-session document as stored in MongoDB."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: ObjectId
    exercise_id: ObjectId
    # The training session (workout) this set-log belongs to, when logged from the
    # agenda flow. Optional so older / standalone logs remain valid.
    workout_id: ObjectId | None = None
    date: datetime
    sets: list[SetDocument]
    notes: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


async def ensure_indexes(db) -> None:
    """Back the session read paths: per-exercise history and personal-best
    (progress, exercise list), per-workout set logs, and the per-user date scans
    that drive the overview streak / breakdown. date is indexed descending to
    favour the common "most recent first" reads (Mongo walks it either way).
    Idempotent — safe to call on every startup."""
    await db[COLLECTION].create_index([("user_id", 1), ("exercise_id", 1), ("date", -1)])
    await db[COLLECTION].create_index([("user_id", 1), ("workout_id", 1)])
    await db[COLLECTION].create_index([("user_id", 1), ("date", -1)])
