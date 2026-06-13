"""Persistence model for the `goals` collection."""
from datetime import datetime

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.helpers.dates import now_utc

COLLECTION = "goals"

# goals.status lifecycle.
STATUS_ACTIVE = "active"
STATUS_ACHIEVED = "achieved"
STATUS_ABANDONED = "abandoned"
GOAL_STATUSES = (STATUS_ACTIVE, STATUS_ACHIEVED, STATUS_ABANDONED)


class GoalDocument(BaseModel):
    """Shape of a goal document as stored in MongoDB."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: ObjectId
    # What the target measures. Free text for now; "weight" is the only metric the
    # trajectory endpoint can project (it needs an exercise to read history from).
    metric: str = "weight"
    exercise_id: ObjectId | None = None
    target_value: float
    target_date: datetime  # stored at midnight UTC of the deadline day
    status: str = STATUS_ACTIVE
    created_at: datetime = Field(default_factory=now_utc)


async def ensure_indexes(db) -> None:
    """Index the goals list query (by owner + status). Idempotent."""
    await db[COLLECTION].create_index([("user_id", 1), ("status", 1)])
