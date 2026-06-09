"""Request / response models for the workouts endpoints."""
from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, Field


class WorkoutCreate(BaseModel):
    date: date_type  # calendar day the session belongs to (YYYY-MM-DD)
    title: str = Field(..., min_length=1)


class WorkoutUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)


class MuscleGroupAdd(BaseModel):
    muscle: str


class WorkoutListItem(BaseModel):
    """One row in GET /workouts (month or single-day listing)."""

    id: str
    date: datetime
    title: str
    muscle_groups: list[str]
    exercise_count: int


class ExerciseInWorkout(BaseModel):
    id: str
    name: str
    emoji: str
    muscle: str
    logged_set_count: int  # sets logged for this exercise within this workout
    last_summary: str | None


class MuscleGroupBlock(BaseModel):
    muscle: str
    exercises: list[ExerciseInWorkout]


class WorkoutDetail(BaseModel):
    """GET /workouts/{id} — the session with its nested muscle groups + exercises."""

    id: str
    date: datetime
    title: str
    muscle_groups: list[MuscleGroupBlock]
