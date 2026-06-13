"""Tiny per-user cache for recap / briefing payloads (Features 8 & 9).

Keyed by ``(user_id, key)`` where ``key`` encodes the period (e.g.
``"recap:2026-W24"``). A cache hit re-serves the stored payload so re-opening the
app spends zero Gemini quota.
"""
from bson import ObjectId

from app.coach.models import COACH_CACHE_COLLECTION, CoachCacheDocument


async def get_cached(db, user_id: ObjectId, key: str) -> dict | None:
    doc = await db[COACH_CACHE_COLLECTION].find_one({"user_id": user_id, "key": key})
    return doc["payload"] if doc else None


async def set_cached(db, user_id: ObjectId, key: str, payload: dict) -> None:
    # Replace (upsert) the whole cache doc so a refresh also refreshes created_at.
    doc = CoachCacheDocument(user_id=user_id, key=key, payload=payload).model_dump()
    await db[COACH_CACHE_COLLECTION].replace_one(
        {"user_id": user_id, "key": key}, doc, upsert=True
    )
