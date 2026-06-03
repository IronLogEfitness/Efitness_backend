from fastapi import APIRouter, Depends, Query
from datetime import datetime, timedelta
from bson import ObjectId
from typing import Optional
from security import get_current_user
from database import get_db

router = APIRouter()

# ─────────────────────────────────────────────────────────
#  GET /progress/overview
#  Overall stats: total sessions, PRs this month,
#  streak, per-muscle breakdown.
# ─────────────────────────────────────────────────────────
@router.get("/overview")
async def get_overview(current_user=Depends(get_current_user), db=Depends(get_db)):
    uid = current_user["_id"]
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Total sessions
    total_sessions = await db["sessions"].count_documents({"user_id": uid})

    # Total sets
    pipeline_sets = [
        {"$match": {"user_id": uid}},
        {"$project": {"count": {"$size": "$sets"}}},
        {"$group": {"_id": None, "total": {"$sum": "$count"}}}
    ]
    sets_result = await db["sessions"].aggregate(pipeline_sets).to_list(1)
    total_sets = sets_result[0]["total"] if sets_result else 0

    # Total exercises
    total_exercises = await db["exercises"].count_documents({"user_id": uid})

    # PRs this month: sessions this month where max weight > all-time PR before that date
    # (simplified: count sessions this month that contain a new max for their exercise)
    prs_this_month = await _count_prs_this_month(db, uid, month_start)

    # Current streak (consecutive days with at least one session, counting backwards from today)
    streak = await _calculate_streak(db, uid)

    # Per-muscle breakdown
    from schema import MUSCLE_GROUPS
    muscle_breakdown = []
    for muscle in MUSCLE_GROUPS:
        ex_ids = await db["exercises"].distinct("_id", {"user_id": uid, "muscle": muscle})
        if not ex_ids:
            muscle_breakdown.append({"muscle": muscle, "total_sessions": 0, "total_sets": 0, "last_trained": None})
            continue

        m_sessions = await db["sessions"].count_documents({"user_id": uid, "exercise_id": {"$in": ex_ids}})
        last = await db["sessions"].find_one(
            {"user_id": uid, "exercise_id": {"$in": ex_ids}},
            sort=[("date", -1)]
        )
        muscle_breakdown.append({
            "muscle":         muscle,
            "total_sessions": m_sessions,
            "last_trained":   last["date"] if last else None,
        })

    return {
        "total_sessions":   total_sessions,
        "total_sets":       total_sets,
        "total_exercises":  total_exercises,
        "prs_this_month":   prs_this_month,
        "current_streak":   streak,
        "muscle_breakdown": muscle_breakdown,
    }


# ─────────────────────────────────────────────────────────
#  GET /progress/exercise/{exercise_id}
#  Weight progression over time for one exercise.
#  Returns data points for a line chart.
# ─────────────────────────────────────────────────────────
@router.get("/exercise/{exercise_id}")
async def get_exercise_progress(
    exercise_id: str,
    days: int = Query(default=90, description="How many days back to look"),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    uid = current_user["_id"]
    since = datetime.utcnow() - timedelta(days=days)

    exercise = await db["exercises"].find_one({
        "_id":     ObjectId(exercise_id),
        "user_id": uid
    })
    if not exercise:
        return {"error": "Exercise not found"}

    sessions = await db["sessions"].find({
        "user_id":     uid,
        "exercise_id": ObjectId(exercise_id),
        "date":        {"$gte": since}
    }).sort("date", 1).to_list(length=200)

    # Build chart data: one point per session = max weight that session
    history = []
    all_time_pr = 0
    for s in sessions:
        max_w = max((st["weight_kg"] for st in s["sets"]), default=0)
        total_reps = sum(st["reps"] for st in s["sets"])
        if max_w > all_time_pr:
            all_time_pr = max_w
        history.append({
            "date":       s["date"],
            "max_weight": max_w,
            "total_sets": len(s["sets"]),
            "total_reps": total_reps,
            "is_pr":      max_w == all_time_pr,
        })

    return {
        "exercise_id":   exercise_id,
        "exercise_name": exercise["name"],
        "emoji":         exercise.get("emoji", "🏋️"),
        "personal_best": all_time_pr,
        "history":       history,
    }


# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────
async def _calculate_streak(db, uid) -> int:
    """Count how many consecutive days (ending today) have at least one session."""
    today = datetime.utcnow().date()
    streak = 0
    day = today
    for _ in range(365):
        start = datetime.combine(day, datetime.min.time())
        end   = datetime.combine(day, datetime.max.time())
        count = await db["sessions"].count_documents({
            "user_id": uid,
            "date":    {"$gte": start, "$lte": end}
        })
        if count > 0:
            streak += 1
            day = day - timedelta(days=1)
        else:
            break
    return streak

async def _count_prs_this_month(db, uid, month_start) -> int:
    """Count exercises that hit a new personal best this month."""
    exercise_ids = await db["exercises"].distinct("_id", {"user_id": uid})
    prs = 0
    for ex_id in exercise_ids:
        # PR before this month
        before = await db["sessions"].aggregate([
            {"$match": {"user_id": uid, "exercise_id": ex_id, "date": {"$lt": month_start}}},
            {"$unwind": "$sets"},
            {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}}
        ]).to_list(1)
        prev_pr = before[0]["max"] if before else 0

        # Max this month
        this_month = await db["sessions"].aggregate([
            {"$match": {"user_id": uid, "exercise_id": ex_id, "date": {"$gte": month_start}}},
            {"$unwind": "$sets"},
            {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}}
        ]).to_list(1)
        this_max = this_month[0]["max"] if this_month else 0

        if this_max > prev_pr:
            prs += 1
    return prs