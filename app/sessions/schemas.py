"""Request / response models for the sessions endpoints."""
from datetime import datetime

from pydantic import BaseModel, Field


class SetIn(BaseModel):
    set_number: int
    weight_kg: float = Field(..., ge=0)
    reps: int = Field(..., ge=1)


class SessionCreate(BaseModel):
    exercise_id: str
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
    date: datetime
    sets: list[SetOut]
    notes: str | None
    created_at: datetime
