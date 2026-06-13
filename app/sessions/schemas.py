"""Request / response models for the sessions endpoints."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.coach.schemas import PRBadge


class SetIn(BaseModel):
    set_number: int
    weight_kg: float = Field(..., ge=0)
    reps: int = Field(..., ge=1)


class SessionCreate(BaseModel):
    exercise_id: str
    workout_id: str | None = None  # the training session this set-log belongs to
    date: datetime | None = None  # defaults to now if omitted
    sets: list[SetIn] = Field(..., min_length=1)
    notes: str | None = None


class SessionUpdate(BaseModel):
    sets: list[SetIn] | None = None
    notes: str | None = None


class SetOut(BaseModel):
    set_number: int
    weight_kg: float
    reps: int


class SessionResponse(BaseModel):
    id: str
    exercise_id: str
    workout_id: str | None = None
    date: datetime
    sets: list[SetOut]
    notes: str | None
    created_at: datetime
    # Set when this log produced a new personal record (heaviest weight ever for the
    # exercise). None otherwise. Computed deterministically — no Gemini call.
    pr: PRBadge | None = None
