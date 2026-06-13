"""Business logic for training goals: CRUD plus a deterministic trajectory.

Every query is scoped to ``user_id`` (from the verified JWT). ``compute_trajectory``
is a pure function (plain dicts in, dict out) so the on/off-track maths is
unit-testable without a DB and spends zero Gemini quota.
"""
from datetime import datetime, time, timezone

from bson import ObjectId

from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.goals.models import (
    COLLECTION,
    GOAL_STATUSES,
    STATUS_ACTIVE,
    GoalDocument,
)
from app.goals.schemas import GoalCreate, GoalResponse, GoalTrajectory, GoalUpdate
from app.helpers.dates import now_utc
from app.helpers.exceptions import BadRequestError, NotFoundError
from app.helpers.objectid import parse_object_id
from app.progress import service as progress_service

# How far back to read history when projecting a goal's trajectory.
TRAJECTORY_LOOKBACK_DAYS = 365


def _day_to_utc_midnight(day) -> datetime:
    """Normalise a calendar date to midnight UTC (matches workouts.service)."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


# ── Trajectory maths (pure, unit-tested) ──
def compute_trajectory(
    history: list[dict],
    target_value: float,
    target_date: datetime,
    now: datetime | None = None,
) -> dict:
    """Project whether a weight goal is on track.

    ``history``      — chronological points ``{"date": datetime, "max_weight": float}``.
    ``target_value`` — goal weight (kg). ``target_date`` — deadline (datetime).

    Slope is the per-day change between the first and last point; the projection
    extends the most recent value forward by the days remaining. Returns a dict
    with ``status`` (``no_data`` | ``achieved`` | ``on_track`` | ``off_track``),
    ``on_track``, ``current_best``, ``current``, ``slope_per_week``,
    ``projected_value`` and ``days_remaining``.
    """
    now = now or now_utc()
    days_remaining = (target_date - now).days

    if not history:
        return {
            "status": "no_data",
            "on_track": False,
            "current_best": None,
            "current": None,
            "slope_per_week": 0.0,
            "projected_value": None,
            "days_remaining": days_remaining,
        }

    current_best = max(p["max_weight"] for p in history)
    current = history[-1]["max_weight"]
    span_days = (history[-1]["date"] - history[0]["date"]).days
    slope_per_day = (
        (history[-1]["max_weight"] - history[0]["max_weight"]) / span_days
        if span_days > 0
        else 0.0
    )

    if current_best >= target_value:
        return {
            "status": "achieved",
            "on_track": True,
            "current_best": current_best,
            "current": current,
            "slope_per_week": round(slope_per_day * 7, 2),
            "projected_value": current_best,
            "days_remaining": days_remaining,
        }

    projected = current + slope_per_day * max(days_remaining, 0)
    on_track = projected >= target_value
    return {
        "status": "on_track" if on_track else "off_track",
        "on_track": on_track,
        "current_best": current_best,
        "current": current,
        "slope_per_week": round(slope_per_day * 7, 2),
        "projected_value": round(projected, 1),
        "days_remaining": days_remaining,
    }


def _verdict(traj: dict, target_value: float) -> str:
    """Templated, zero-quota verdict line for a trajectory."""
    status = traj["status"]
    if status == "no_data":
        return "Not enough history yet to project — log a few sessions for this lift."
    if status == "achieved":
        return f"🎉 You've already hit {target_value}kg — goal achieved!"
    projected = traj["projected_value"]
    if status == "on_track":
        return (
            f"On track — at your current pace you'll reach ~{projected}kg by the "
            f"deadline (target {target_value}kg)."
        )
    return (
        f"Behind pace — projected ~{projected}kg vs a {target_value}kg target. "
        f"Tighten up progression or extend the deadline."
    )


# ── Serialiser ──
async def _exercise_name(db, user_id: ObjectId, exercise_id) -> str | None:
    if exercise_id is None:
        return None
    ex = await db[EXERCISES_COLLECTION].find_one({"_id": exercise_id, "user_id": user_id})
    return ex["name"] if ex else None


async def _to_response(db, user_id: ObjectId, doc: dict) -> GoalResponse:
    return GoalResponse(
        id=str(doc["_id"]),
        metric=doc.get("metric", "weight"),
        exercise_id=str(doc["exercise_id"]) if doc.get("exercise_id") else None,
        exercise_name=await _exercise_name(db, user_id, doc.get("exercise_id")),
        target_value=doc["target_value"],
        target_date=doc["target_date"],
        status=doc.get("status", STATUS_ACTIVE),
        created_at=doc["created_at"],
    )


# ── CRUD ──
async def _require_goal(db, user_id: ObjectId, goal_id: str) -> dict:
    oid = parse_object_id(goal_id, "goal id")
    doc = await db[COLLECTION].find_one({"_id": oid, "user_id": user_id})
    if not doc:
        raise NotFoundError("Goal not found")
    return doc


async def create_goal(db, user_id: ObjectId, body: GoalCreate) -> GoalResponse:
    exercise_oid = None
    if body.exercise_id:
        exercise_oid = parse_object_id(body.exercise_id, "exercise id")
        ex = await db[EXERCISES_COLLECTION].find_one(
            {"_id": exercise_oid, "user_id": user_id}
        )
        if not ex:
            raise NotFoundError("Exercise not found")

    doc = GoalDocument(
        user_id=user_id,
        metric=body.metric.strip() or "weight",
        exercise_id=exercise_oid,
        target_value=body.target_value,
        target_date=_day_to_utc_midnight(body.target_date),
    ).model_dump()
    result = await db[COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return await _to_response(db, user_id, doc)


async def list_goals(
    db, user_id: ObjectId, status: str | None = None
) -> list[GoalResponse]:
    query: dict = {"user_id": user_id}
    if status:
        query["status"] = status
    docs = await db[COLLECTION].find(query).sort("created_at", -1).to_list(length=200)
    return [await _to_response(db, user_id, d) for d in docs]


async def get_goal(db, user_id: ObjectId, goal_id: str) -> GoalResponse:
    return await _to_response(db, user_id, await _require_goal(db, user_id, goal_id))


async def update_goal(
    db, user_id: ObjectId, goal_id: str, body: GoalUpdate
) -> GoalResponse:
    oid = parse_object_id(goal_id, "goal id")

    update: dict = {}
    if body.target_value is not None:
        update["target_value"] = body.target_value
    if body.target_date is not None:
        update["target_date"] = _day_to_utc_midnight(body.target_date)
    if body.status is not None:
        if body.status not in GOAL_STATUSES:
            raise BadRequestError(f"Invalid status. Choose from: {list(GOAL_STATUSES)}")
        update["status"] = body.status
    if not update:
        raise BadRequestError("Nothing to update")

    doc = await db[COLLECTION].find_one_and_update(
        {"_id": oid, "user_id": user_id}, {"$set": update}, return_document=True
    )
    if not doc:
        raise NotFoundError("Goal not found")
    return await _to_response(db, user_id, doc)


async def delete_goal(db, user_id: ObjectId, goal_id: str) -> None:
    oid = parse_object_id(goal_id, "goal id")
    result = await db[COLLECTION].delete_one({"_id": oid, "user_id": user_id})
    if result.deleted_count == 0:
        raise NotFoundError("Goal not found")


# ── Trajectory ──
async def get_trajectory(db, user_id: ObjectId, goal_id: str) -> GoalTrajectory:
    goal = await _require_goal(db, user_id, goal_id)

    history: list[dict] = []
    if goal.get("exercise_id"):
        prog = await progress_service.get_exercise_progress(
            db, user_id, str(goal["exercise_id"]), days=TRAJECTORY_LOOKBACK_DAYS
        )
        history = [{"date": p.date, "max_weight": p.max_weight} for p in prog.history]

    traj = compute_trajectory(history, goal["target_value"], goal["target_date"])
    return GoalTrajectory(
        goal_id=str(goal["_id"]),
        target_value=goal["target_value"],
        verdict=_verdict(traj, goal["target_value"]),
        **traj,
    )
