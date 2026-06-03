from datetime import datetime

from pydantic import BaseModel


class MuscleSummary(BaseModel):
    muscle: str
    exercise_count: int
    last_trained: datetime | None
