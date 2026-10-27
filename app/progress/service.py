"""Read-only analytics: overall stats and per-exercise weight progression."""
from datetime import date, timedelta

from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.helpers.exceptions import NotFoundError
from app.helpers.objectid import parse_object_id
from app.muscles.constants import MUSCLE_GROUPS
from app.progress.schemas import (
    ExerciseProgressResponse,
    MuscleStats,
    OverviewResponse,
    ProgressPoint,
)
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION


async def _count_sets(db, match: dict) -> int:
    """Total number of sets across the sessions matching `match`."""
    agg = await db[SESSIONS_COLLECTION].aggregate(
        [
            {"$match": match},
            {"$project": {"count": {"$size": "$sets"}}},
            {"$group": {"_id": None, "total": {"$sum": "$count"}}},
        ]
    ).to_list(1)
    return agg[0]["total"] if agg else 0


async def get_overview(db, user_id) -> OverviewResponse:
    now = now_utc()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_sessions = await db[SESSIONS_COLLECTION].count_documents({"user_id": user_id})
    total_sets = await _count_sets(db, {"user_id": user_id})
    total_exercises = await db[EXERCISES_COLLECTION].count_documents({"user_id": user_id})
    prs_this_month = await _count_prs_this_month(db, user_id, month_start)
    streak = await _calculate_streak(db, user_id)
    muscle_breakdown = await _muscle_breakdown(db, user_id)

    return OverviewResponse(
        total_sessions=total_sessions,
        total_sets=total_sets,
        total_exercises=total_exercises,
        prs_this_month=prs_this_month,
        current_streak=streak,
        muscle_breakdown=muscle_breakdown,
    )


async def get_exercise_progress(
    db, user_id, exercise_id: str, days: int = 90
) -> ExerciseProgressResponse:
    oid = parse_object_id(exercise_id, "exercise id")
    since = now_utc() - timedelta(days=days)

    exercise = await db[EXERCISES_COLLECTION].find_one({"_id": oid, "user_id": user_id})
    if not exercise:
        raise NotFoundError("Exercise not found")

    sessions = await db[SESSIONS_COLLECTION].find(
        {"user_id": user_id, "exercise_id": oid, "date": {"$gte": since}}
    ).sort("date", 1).to_list(length=200)

    # One chart point per session = the max weight lifted that session.
    history: list[ProgressPoint] = []
    all_time_pr = 0.0
    for s in sessions:
        max_w = max((st["weight_kg"] for st in s["sets"]), default=0)
        total_reps = sum(st["reps"] for st in s["sets"])
        if max_w > all_time_pr:
            all_time_pr = max_w
        history.append(
            ProgressPoint(
                date=s["date"],
                max_weight=max_w,
                total_sets=len(s["sets"]),
                total_reps=total_reps,
                is_pr=max_w == all_time_pr,
            )
        )

    return ExerciseProgressResponse(
        exercise_id=exercise_id,
        exercise_name=exercise["name"],
        emoji=exercise.get("emoji", "🏋️"),
        personal_best=all_time_pr,
        history=history,
    )


# ── Helpers ──
def compute_streak(session_days: set[date], today: date) -> int:
    """Number of consecutive days up to and including ``today`` that are present
    in ``session_days``. 0 when today itself has no session. Capped at 365 to
    mirror the previous bounded day-by-day scan.

    Pure (no DB) so it can be unit-tested directly; ``_calculate_streak`` feeds
    it the set of UTC days on which the user trained.
    """
    streak = 0
    day = today
    while day in session_days and streak < 365:
        streak += 1
        day -= timedelta(days=1)
    return streak


async def _calculate_streak(db, user_id) -> int:
    """How many consecutive days (ending today, UTC) have at least one session.

    One aggregation groups the user's sessions into the distinct UTC days they
    trained; the consecutive-day count is then computed in ``compute_streak``.
    ($dateToString defaults to UTC, matching the UTC-stored session dates.)
    """
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}}}},
    ]
    rows = await db[SESSIONS_COLLECTION].aggregate(pipeline).to_list(length=None)
    session_days = {date.fromisoformat(r["_id"]) for r in rows}
    return compute_streak(session_days, now_utc().date())


async def _count_prs_this_month(db, user_id, month_start) -> int:
    """Number of exercises whose heaviest set this month beats their heaviest set
    from before this month.

    One aggregation over all the user's sessions (previously two aggregations per
    exercise): group by exercise, taking the max weight on each side of
    ``month_start``. An exercise with no prior history has prev_max None → 0, so a
    brand-new exercise that logged any weight this month still counts as a PR —
    identical to the previous per-exercise logic.
    """
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$unwind": "$sets"},
        {
            "$group": {
                "_id": "$exercise_id",
                "prev_max": {
                    "$max": {"$cond": [{"$lt": ["$date", month_start]}, "$sets.weight_kg", None]}
                },
                "month_max": {
                    "$max": {"$cond": [{"$gte": ["$date", month_start]}, "$sets.weight_kg", None]}
                },
            }
        },
    ]
    rows = await db[SESSIONS_COLLECTION].aggregate(pipeline).to_list(length=None)
    return sum(1 for r in rows if (r["month_max"] or 0) > (r["prev_max"] or 0))


async def _muscle_breakdown(db, user_id) -> list[MuscleStats]:
    """Per-muscle session count, set count, and last-trained date — all 8 muscle
    groups in ``MUSCLE_GROUPS`` order, zeros/None for ones not yet trained.

    One aggregation (previously a distinct + count + set-count + find_one per
    muscle): a session's muscle is its exercise's muscle, so join sessions →
    exercises and group by ``exercise.muscle``. Sessions whose exercise no longer
    exists are dropped by ``$unwind``, exactly as the old id-filtered counts did.
    """
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$lookup": {
                "from": EXERCISES_COLLECTION,
                "localField": "exercise_id",
                "foreignField": "_id",
                "as": "exercise",
            }
        },
        {"$unwind": "$exercise"},
        {
            "$group": {
                "_id": "$exercise.muscle",
                "total_sessions": {"$sum": 1},
                "total_sets": {"$sum": {"$size": "$sets"}},
                "last_trained": {"$max": "$date"},
            }
        },
    ]
    rows = {
        r["_id"]: r
        for r in await db[SESSIONS_COLLECTION].aggregate(pipeline).to_list(length=None)
    }
    breakdown: list[MuscleStats] = []
    for muscle in MUSCLE_GROUPS:
        r = rows.get(muscle)
        breakdown.append(
            MuscleStats(
                muscle=muscle,
                total_sessions=r["total_sessions"] if r else 0,
                total_sets=r["total_sets"] if r else 0,
                last_trained=r["last_trained"] if r else None,
            )
        )
    return breakdown
