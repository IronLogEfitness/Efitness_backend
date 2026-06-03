"""Persistence model for the `exercises` collection."""
from datetime import datetime

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

from app.helpers.dates import now_utc

COLLECTION = "exercises"


class ExerciseDocument(BaseModel):
    """Shape of an exercise document as stored in MongoDB."""

    # arbitrary_types_allowed lets us keep `user_id` as a real ObjectId, so
    # model_dump() produces a dict ready to hand straight to Motor.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: ObjectId
    muscle: str
    name: str
    emoji: str = "🏋️"
    image_url: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
