"""Feature 9 — pre-workout briefing.

A single line for "today": what's planned, and a target drawn from the last time
the same session was trained ("Beat last week's 3×8 row at 50kg"). Composed
deterministically by default (Gemini optional, off), cached per ``(user, date)`` so
re-opening the app costs nothing. Trigger is app-open (a GET), never a cron.
"""
from datetime import datetime, time, timedelta, timezone

from bson import ObjectId

from app.chat import gemini
from app.coach import cache
from app.coach.schemas import BriefingResponse
from app.config import settings
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.helpers.exceptions import AppError
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION
from app.workouts.models import COLLECTION as WORKOUTS_COLLECTION


def _day_bounds(day) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


async def _last_same_session(db, user_id: ObjectId, title: str, before: datetime) -> str | None:
    """A short summary of the last time this session title was trained, e.g.
    'Barbell Row 50kg×8' — or None if there's nothing to beat."""
    w = await db[WORKOUTS_COLLECTION].find_one(
        {"user_id": user_id, "title": title, "date": {"$lt": before}},
        sort=[("date", -1)],
    )
    if not w:
        return None
    log = await db[SESSIONS_COLLECTION].find_one(
        {"user_id": user_id, "workout_id": w["_id"]}, sort=[("date", -1)]
    )
    if not log or not log.get("sets"):
        return None
    ex = await db[EXERCISES_COLLECTION].find_one(
        {"_id": log["exercise_id"], "user_id": user_id}
    )
    name = ex["name"] if ex else "your last lift"
    sets_text = ", ".join(f"{st['weight_kg']:g}kg×{st['reps']}" for st in log["sets"])
    return f"{name} {sets_text}"


def _template_text(title: str | None, last: str | None) -> str:
    if title is None:
        return "No session planned today. Want me to plan one?"
    if last:
        return f"Today: {title}. Beat last time's {last}. Let's go. 💪"
    return f"Today: {title}. First time logging this one — set the bar. 💪"


async def get_briefing(db, user_id: ObjectId) -> BriefingResponse:
    today = now_utc().date()
    key = f"briefing:{today.isoformat()}"

    cached = await cache.get_cached(db, user_id, key)
    if cached:
        return BriefingResponse(**cached, cached=True)

    start, end = _day_bounds(today)
    workout = await db[WORKOUTS_COLLECTION].find_one(
        {"user_id": user_id, "date": {"$gte": start, "$lt": end}}, sort=[("date", 1)]
    )
    title = workout["title"] if workout else None
    last = (
        await _last_same_session(db, user_id, title, start) if workout else None
    )

    text = _template_text(title, last)
    if title is not None and settings.COACH_BRIEFING_USE_LLM:
        try:
            text, _ = await gemini.compose(
                "You are IronLog's coach. Write ONE punchy pre-workout line (<25 "
                "words) for today's session. If a previous result is given, set a "
                "target to beat it.",
                f"Today's session: {title}. Last time: {last or 'no prior data'}.",
            )
        except AppError:
            pass  # keep the template

    payload = {
        "date": start.isoformat(),
        "has_workout": workout is not None,
        "title": title,
        "text": text,
    }
    await cache.set_cached(db, user_id, key, payload)
    return BriefingResponse(**payload, cached=False)
