"""Request / response models for the exercises endpoints."""
from pydantic import BaseModel, Field


class ExerciseCreate(BaseModel):
    muscle: str = Field(..., description="e.g. chest")
    name: str = Field(..., min_length=2)
    emoji: str = Field(default="🏋️")
    image_url: str | None = None


class ExerciseUpdate(BaseModel):
    name: str | None = None
    emoji: str | None = None
    image_url: str | None = None


class SetSummary(BaseModel):
    set_number: int
    weight_kg: float
    reps: int


class LastSession(BaseModel):
    id: str
    notes: str | None
    sets: list[SetSummary]


class ExerciseListItem(BaseModel):
    """One row in GET /exercises (and the body returned by POST /exercises)."""

    id: str
    muscle: str
    name: str
    emoji: str
    image_url: str | None
    personal_best: float | None
    last_session_summary: str | None
    set_count: int | None


class ExerciseDetail(BaseModel):
    """GET /exercises/{id}."""

    id: str
    muscle: str
    name: str
    emoji: str
    image_url: str | None
    personal_best: float | None
    last_session: LastSession | None
