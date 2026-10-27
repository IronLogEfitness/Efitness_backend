"""Persistence model for the `workouts` collection.

A *workout* is a training session for a given day (e.g. "Morning Push"). It is the
top-level entry point of the agenda flow: it carries a title, a calendar date, and the
list of muscle groups worked. The actual logged sets live in the `sessions` collection
(per-exercise set logs) and link back here via their `workout_id`.
"""
from datetime import datetime

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.helpers.dates import now_utc

COLLECTION = "workouts"


class WorkoutDocument(BaseModel):
    """Shape of a workout document as stored in MongoDB."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: ObjectId
    # Stored at midnight UTC of the calendar day the session belongs to.
    date: datetime
    title: str
    # Lowercase muscle names from app.muscles.constants.MUSCLE_GROUPS.
    muscle_groups: list[str] = Field(default_factory=list)
    # Which catalog exercises belong to THIS workout. Exercises live in the shared
    # `exercises` collection (so personal-best / progress / coach keep tracking each
    # by a stable id across sessions), but a workout only shows the ones explicitly
    # added to — or logged in — it. Empty on a fresh workout, so a new session starts
    # blank instead of inheriting every exercise ever made for the muscle.
    exercise_ids: list[ObjectId] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now_utc)
    # Bumped on title/date/membership changes; present for future sync / debugging.
    updated_at: datetime = Field(default_factory=now_utc)


async def ensure_indexes(db) -> None:
    """Back the per-user agenda reads (workouts listed/looked up by date).
    Idempotent — safe to call on every startup."""
    await db[COLLECTION].create_index([("user_id", 1), ("date", -1)])
