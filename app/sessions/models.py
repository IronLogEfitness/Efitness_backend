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
    date: datetime
    sets: list[SetDocument]
    notes: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
