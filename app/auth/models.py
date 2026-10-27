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


async def ensure_indexes(db) -> None:
    """Enforce one account per email address. The unique index is what makes
    registration race-safe: two concurrent requests can both pass the friendly
    ``find_one`` pre-check, but only one insert survives — the other raises
    ``DuplicateKeyError`` (caught in ``service.register``). Idempotent — safe to
    call on every startup."""
    await db[COLLECTION].create_index([("email", 1)], unique=True)
