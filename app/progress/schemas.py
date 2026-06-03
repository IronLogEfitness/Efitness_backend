"""Response models for the progress / stats endpoints."""
from datetime import datetime

from pydantic import BaseModel


class MuscleStats(BaseModel):
    muscle: str
    total_sessions: int
    total_sets: int
    last_trained: datetime | None


class OverviewResponse(BaseModel):
    total_sessions: int
    total_sets: int
    total_exercises: int
    prs_this_month: int
    current_streak: int  # consecutive days with at least one session
    muscle_breakdown: list[MuscleStats]


class ProgressPoint(BaseModel):
    date: datetime
    max_weight: float
    total_sets: int
    total_reps: int
    is_pr: bool


class ExerciseProgressResponse(BaseModel):
    exercise_id: str
    exercise_name: str
    emoji: str
    personal_best: float
    history: list[ProgressPoint]
