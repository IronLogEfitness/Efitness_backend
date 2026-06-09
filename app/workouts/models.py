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
    created_at: datetime = Field(default_factory=now_utc)
