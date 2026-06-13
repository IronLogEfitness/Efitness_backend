"""Execute one confirmed action by resolving its human refs and calling the
existing domain services — so a chat-driven write is byte-for-byte the same record
a manual one would produce, and stays reversible via the same delete endpoints.

Each handler returns an ``ExecResult`` (``created_id`` + optional ``pr`` badge +
``detail``). It may raise:
  - ``resolve.NeedsClarification`` → the caller marks the action ``needs_clarification``,
  - ``AppError`` (from a service) → the caller marks it ``failed``.
Neither ever crashes the request.
"""
from dataclasses import dataclass

from bson import ObjectId

from app.coach import prs, resolve
from app.exercises.schemas import ExerciseCreate
from app.exercises.service import create_exercise as svc_create_exercise
from app.goals.schemas import GoalCreate, GoalUpdate
from app.goals.service import create_goal as svc_create_goal
from app.goals.service import update_goal as svc_update_goal
from app.helpers.exceptions import BadRequestError
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION
from app.sessions.schemas import SessionCreate, SetIn
from app.sessions.service import create_session as svc_create_session
from app.workouts.schemas import WorkoutCreate, WorkoutUpdate
from app.workouts.service import add_muscle_group as svc_add_muscle_group
from app.workouts.service import create_workout as svc_create_workout
from app.workouts.service import delete_workout as svc_delete_workout
from app.workouts.service import update_workout as svc_update_workout


@dataclass
class ExecResult:
    created_id: str | None = None
    detail: str = ""
    pr: dict | None = None


async def _previous_best(db, user_id: ObjectId, exercise_id: ObjectId) -> float | None:
    """Heaviest weight ever logged for this exercise (before the current insert)."""
    agg = await db[SESSIONS_COLLECTION].aggregate(
        [
            {"$match": {"user_id": user_id, "exercise_id": exercise_id}},
            {"$unwind": "$sets"},
            {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
        ]
    ).to_list(1)
    return agg[0]["max"] if agg else None


def _require_date(ref: str, field_name: str = "date"):
    day = resolve.parse_date_ref(ref)
    if day is None:
        raise resolve.NeedsClarification(
            f"I couldn't read '{ref}' as a {field_name}. Use 'today', 'tomorrow', "
            f"or a date like 2026-06-13."
        )
    return day


# ── Per-type handlers ──
async def _create_workout(db, user_id, args) -> ExecResult:
    day = _require_date(args["date"])
    item = await svc_create_workout(
        db, user_id, WorkoutCreate(date=day.date(), title=args["title"])
    )
    return ExecResult(created_id=item.id, detail=f"Created workout '{item.title}'.")


async def _add_muscle_group(db, user_id, args) -> ExecResult:
    wid, _ = await resolve.resolve_workout(db, user_id, args["workout_ref"], create=True)
    await svc_add_muscle_group(db, user_id, str(wid), args["muscle"])
    return ExecResult(created_id=str(wid), detail=f"Added {args['muscle']} to the workout.")


async def _create_exercise(db, user_id, args) -> ExecResult:
    created = await svc_create_exercise(
        db,
        user_id,
        ExerciseCreate(
            muscle=args["muscle"], name=args["name"], emoji=args.get("emoji") or "🏋️"
        ),
    )
    return ExecResult(created_id=created["id"], detail=f"Created exercise '{created['name']}'.")


async def _log_sets(db, user_id, args) -> ExecResult:
    wid, _ = await resolve.resolve_workout(
        db, user_id, args.get("workout_ref") or "today", create=True
    )
    eid, _ = await resolve.resolve_exercise(
        db, user_id, args["exercise_ref"], muscle_hint=args.get("muscle"), create=True
    )

    # Snapshot the prior best BEFORE inserting, so PR detection is correct.
    prev_best = await _previous_best(db, user_id, eid)
    sets = [SetIn(**s) for s in args["sets"]]
    session = await svc_create_session(
        db,
        user_id,
        SessionCreate(
            exercise_id=str(eid),
            workout_id=str(wid),
            sets=sets,
            notes=args.get("notes"),
        ),
    )
    badge = prs.detect_pr([s.model_dump() for s in sets], prev_best)
    detail = f"Logged {len(sets)} set(s)."
    if badge:
        detail += f" 🏆 New PR at {badge['value']}kg!"
    return ExecResult(created_id=session.id, detail=detail, pr=badge)


async def _move_workout(db, user_id, args) -> ExecResult:
    wid, _ = await resolve.resolve_workout(db, user_id, args["workout_ref"], create=False)
    day = _require_date(args["new_date"], "new date")
    await svc_update_workout(db, user_id, str(wid), WorkoutUpdate(date=day.date()))
    return ExecResult(created_id=str(wid), detail=f"Moved workout to {day.date().isoformat()}.")


async def _update_workout_title(db, user_id, args) -> ExecResult:
    wid, _ = await resolve.resolve_workout(db, user_id, args["workout_ref"], create=False)
    await svc_update_workout(db, user_id, str(wid), WorkoutUpdate(title=args["title"]))
    return ExecResult(created_id=str(wid), detail=f"Renamed workout to '{args['title']}'.")


async def _delete_workout(db, user_id, args) -> ExecResult:
    wid, _ = await resolve.resolve_workout(db, user_id, args["workout_ref"], create=False)
    await svc_delete_workout(db, user_id, str(wid))
    return ExecResult(created_id=str(wid), detail="Deleted the workout and its logged sets.")


async def _create_goal(db, user_id, args) -> ExecResult:
    exercise_id = None
    if args.get("exercise_ref"):
        eid, _ = await resolve.resolve_exercise(
            db, user_id, args["exercise_ref"], create=False
        )
        exercise_id = str(eid)
    day = _require_date(args["target_date"], "target date")
    goal = await svc_create_goal(
        db,
        user_id,
        GoalCreate(
            metric=args.get("metric") or "weight",
            exercise_id=exercise_id,
            target_value=args["target_value"],
            target_date=day.date(),
        ),
    )
    return ExecResult(created_id=goal.id, detail=f"Set a goal of {goal.target_value}kg.")


async def _update_goal(db, user_id, args) -> ExecResult:
    day = None
    if args.get("target_date"):
        day = _require_date(args["target_date"], "target date")
    goal = await svc_update_goal(
        db,
        user_id,
        args["goal_id"],
        GoalUpdate(
            target_value=args.get("target_value"),
            target_date=day.date() if day else None,
            status=args.get("status"),
        ),
    )
    return ExecResult(created_id=goal.id, detail="Updated the goal.")


# Dispatch table: action type → handler. Also defines the dependency-safe execution
# order (creates before the rows that reference them) used by the confirm step.
_HANDLERS = {
    "create_workout": _create_workout,
    "create_exercise": _create_exercise,
    "add_muscle_group": _add_muscle_group,
    "log_sets": _log_sets,
    "move_workout": _move_workout,
    "update_workout_title": _update_workout_title,
    "delete_workout": _delete_workout,
    "create_goal": _create_goal,
    "update_goal": _update_goal,
}

# Lower number = executed earlier within one confirm batch, so dependencies exist
# before dependents (e.g. create_workout/create_exercise before log_sets).
EXECUTION_ORDER = {
    "create_workout": 0,
    "create_exercise": 0,
    "add_muscle_group": 1,
    "log_sets": 2,
    "create_goal": 2,
    "move_workout": 3,
    "update_workout_title": 3,
    "update_goal": 3,
    "delete_workout": 4,
}


async def execute_action(db, user_id: ObjectId, action_type: str, args: dict) -> ExecResult:
    """Run one resolved action. Raises ``NeedsClarification`` or ``AppError``."""
    handler = _HANDLERS.get(action_type)
    if handler is None:
        raise BadRequestError(f"Unknown action type: {action_type}")
    return await handler(db, user_id, args)
