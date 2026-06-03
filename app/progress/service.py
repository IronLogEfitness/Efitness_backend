"""Read-only analytics: overall stats and per-exercise weight progression."""
from datetime import datetime, time, timedelta, timezone

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

    muscle_breakdown: list[MuscleStats] = []
    for muscle in MUSCLE_GROUPS:
        ex_ids = await db[EXERCISES_COLLECTION].distinct(
            "_id", {"user_id": user_id, "muscle": muscle}
        )
        if not ex_ids:
            muscle_breakdown.append(
                MuscleStats(muscle=muscle, total_sessions=0, total_sets=0, last_trained=None)
            )
            continue

        match = {"user_id": user_id, "exercise_id": {"$in": ex_ids}}
        m_sessions = await db[SESSIONS_COLLECTION].count_documents(match)
        m_sets = await _count_sets(db, match)
        last = await db[SESSIONS_COLLECTION].find_one(match, sort=[("date", -1)])
        muscle_breakdown.append(
            MuscleStats(
                muscle=muscle,
                total_sessions=m_sessions,
                total_sets=m_sets,
                last_trained=last["date"] if last else None,
            )
        )

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
async def _calculate_streak(db, user_id) -> int:
    """How many consecutive days (ending today) have at least one session."""
    today = now_utc().date()
    streak = 0
    day = today
    for _ in range(365):
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day, time.max, tzinfo=timezone.utc)
        count = await db[SESSIONS_COLLECTION].count_documents(
            {"user_id": user_id, "date": {"$gte": start, "$lte": end}}
        )
        if count > 0:
            streak += 1
            day = day - timedelta(days=1)
        else:
            break
    return streak


async def _count_prs_this_month(db, user_id, month_start) -> int:
    """Number of exercises that hit a new personal best this month."""
    exercise_ids = await db[EXERCISES_COLLECTION].distinct("_id", {"user_id": user_id})
    prs = 0
    for ex_id in exercise_ids:
        before = await db[SESSIONS_COLLECTION].aggregate(
            [
                {"$match": {"user_id": user_id, "exercise_id": ex_id, "date": {"$lt": month_start}}},
                {"$unwind": "$sets"},
                {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
            ]
        ).to_list(1)
        prev_pr = before[0]["max"] if before else 0

        this_month = await db[SESSIONS_COLLECTION].aggregate(
            [
                {"$match": {"user_id": user_id, "exercise_id": ex_id, "date": {"$gte": month_start}}},
                {"$unwind": "$sets"},
                {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
            ]
        ).to_list(1)
        this_max = this_month[0]["max"] if this_month else 0

        if this_max > prev_pr:
            prs += 1
    return prs
