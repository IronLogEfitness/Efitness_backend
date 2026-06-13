"""Request / response models for the goals endpoints."""
from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, Field

from app.goals.models import GOAL_STATUSES


class GoalCreate(BaseModel):
    metric: str = Field(default="weight", description="What the target measures")
    exercise_id: str | None = None
    target_value: float = Field(..., gt=0)
    target_date: date_type


class GoalUpdate(BaseModel):
    target_value: float | None = Field(default=None, gt=0)
    target_date: date_type | None = None
    status: str | None = Field(default=None, description=f"One of {GOAL_STATUSES}")


class GoalResponse(BaseModel):
    id: str
    metric: str
    exercise_id: str | None
    exercise_name: str | None
    target_value: float
    target_date: datetime
    status: str
    created_at: datetime


class GoalTrajectory(BaseModel):
    goal_id: str
    # no_data | on_track | off_track | achieved
    status: str
    on_track: bool
    current_best: float | None
    current: float | None
    slope_per_week: float
    projected_value: float | None
    days_remaining: int
    target_value: float
    verdict: str
