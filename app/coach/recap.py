"""Feature 8 — weekly "wrapped" recap.

The week is aggregated **deterministically** (sessions, sets, PRs, streak, best
lift) in plain code; then at most ONE Gemini call writes the recap prose, and the
whole payload is cached per ``(user, ISO-week)`` so re-opening the app re-serves it
for free. Trigger is app-open (a GET), never a background cron.
"""
from datetime import datetime, time, timedelta, timezone

from bson import ObjectId

from app.chat import gemini
from app.coach import cache
from app.coach.schemas import RecapResponse
from app.config import settings
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.helpers.exceptions import AppError, BadRequestError
from app.progress import service as progress_service
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION
from app.workouts.models import COLLECTION as WORKOUTS_COLLECTION


def current_iso_week(today=None) -> str:
    today = today or now_utc().date()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def _week_range(week: str) -> tuple[datetime, datetime]:
    """``"YYYY-Www"`` → (Monday 00:00 UTC, next Monday 00:00 UTC)."""
    try:
        year_s, week_s = week.split("-W")
        monday = datetime.fromisocalendar(int(year_s), int(week_s), 1).date()
    except (ValueError, AttributeError):
        raise BadRequestError("week must look like 2026-W24")
    start = datetime.combine(monday, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


async def _aggregate_week(db, user_id: ObjectId, start: datetime, end: datetime) -> dict:
    total_sessions = await db[WORKOUTS_COLLECTION].count_documents(
        {"user_id": user_id, "date": {"$gte": start, "$lt": end}}
    )

    sessions = await db[SESSIONS_COLLECTION].find(
        {"user_id": user_id, "date": {"$gte": start, "$lt": end}}
    ).to_list(length=1000)

    total_sets = 0
    best_weight = 0.0
    best_exercise_id = None
    week_max: dict = {}  # exercise_id -> max weight this week
    for s in sessions:
        total_sets += len(s["sets"])
        for st in s["sets"]:
            w = st["weight_kg"]
            if w > best_weight:
                best_weight, best_exercise_id = w, s["exercise_id"]
            if w > week_max.get(s["exercise_id"], 0):
                week_max[s["exercise_id"]] = w

    # PRs this week: an exercise whose best set this week beats its best before the week.
    prs = 0
    for ex_id, wk_max in week_max.items():
        before = await db[SESSIONS_COLLECTION].aggregate([
            {"$match": {"user_id": user_id, "exercise_id": ex_id, "date": {"$lt": start}}},
            {"$unwind": "$sets"},
            {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
        ]).to_list(1)
        prev = before[0]["max"] if before else 0
        if wk_max > prev:
            prs += 1

    best_lift = None
    if best_exercise_id is not None:
        ex = await db[EXERCISES_COLLECTION].find_one(
            {"_id": best_exercise_id, "user_id": user_id}
        )
        name = ex["name"] if ex else "a lift"
        best_lift = f"{best_weight:g}kg on {name}"

    overview = await progress_service.get_overview(db, user_id)
    return {
        "total_sessions": total_sessions,
        "total_sets": total_sets,
        "prs": prs,
        "streak": overview.current_streak,
        "best_lift": best_lift,
    }


def _template_text(agg: dict) -> str:
    bits = [f"{agg['total_sessions']} sessions, {agg['total_sets']} sets"]
    if agg["prs"]:
        bits.append(f"{agg['prs']} new PR{'s' if agg['prs'] != 1 else ''}")
    if agg["best_lift"]:
        bits.append(f"best lift {agg['best_lift']}")
    if agg["streak"]:
        bits.append(f"{agg['streak']}-day streak")
    return "This week: " + ", ".join(bits) + ". Keep the momentum into next week!"


async def _recap_text(agg: dict) -> str:
    if not settings.COACH_RECAP_USE_LLM:
        return _template_text(agg)
    facts = (
        f"sessions={agg['total_sessions']}, sets={agg['total_sets']}, "
        f"new_prs={agg['prs']}, streak_days={agg['streak']}, best_lift={agg['best_lift']}"
    )
    try:
        text, _ = await gemini.compose(
            "You are IronLog's coach writing a short weekly 'wrapped' recap. Use the "
            "exact numbers given. 2-3 sentences, upbeat and specific, then one line "
            "proposing next week's focus.",
            f"This week's stats: {facts}",
        )
        return text
    except AppError:
        return _template_text(agg)  # best-effort


async def get_recap(db, user_id: ObjectId, week: str | None) -> RecapResponse:
    week = week or current_iso_week()
    key = f"recap:{week}"

    cached = await cache.get_cached(db, user_id, key)
    if cached:
        return RecapResponse(**cached, cached=True)

    start, end = _week_range(week)
    agg = await _aggregate_week(db, user_id, start, end)
    payload = {"week": week, "text": await _recap_text(agg), **agg}
    await cache.set_cached(db, user_id, key, payload)
    return RecapResponse(**payload, cached=False)
