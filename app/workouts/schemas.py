"""Request / response models for the workouts endpoints."""
from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, Field


class WorkoutCreate(BaseModel):
    date: date_type  # calendar day the session belongs to (YYYY-MM-DD)
    title: str = Field(..., min_length=1)


class WorkoutUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    # Reschedule the workout to another day (its logged sets move with it, since
    # sets link by workout_id, not by date). Used by PATCH /workouts/{id}.
    date: date_type | None = None


class MuscleGroupAdd(BaseModel):
    muscle: str


class WorkoutExerciseAdd(BaseModel):
    """Add an exercise to one workout's muscle block.

    The exercise is found-or-created in the shared catalog by (muscle, name) so a
    re-used name keeps its tracking history; only the membership link is new.
    """

    muscle: str
    name: str = Field(..., min_length=2)
    emoji: str = Field(default="🏋️")
    image_url: str | None = None


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
    image_url: str | None = None


class MuscleGroupBlock(BaseModel):
    muscle: str
    exercises: list[ExerciseInWorkout]


class WorkoutDetail(BaseModel):
    """GET /workouts/{id} — the session with its nested muscle groups + exercises."""

    id: str
    date: datetime
    title: str
    muscle_groups: list[MuscleGroupBlock]
