"""Persistence model for the `users` collection."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.helpers.dates import now_utc

COLLECTION = "users"


class UserDocument(BaseModel):
    """Shape of a user document as stored in MongoDB (password is hashed)."""

    name: str
    email: str
    password: str
    username: str | None = None
    gender: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    created_at: datetime = Field(default_factory=now_utc)
