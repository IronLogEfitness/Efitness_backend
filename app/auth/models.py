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
    created_at: datetime = Field(default_factory=now_utc)
