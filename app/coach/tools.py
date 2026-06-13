"""The coach's tool registry — the single source of truth for what Gemini can do.

Three things live here, keyed by tool name:
  1. ``DECLARATIONS`` — the Gemini ``FunctionDeclaration`` schemas sent on every
     tool-enabled turn.
  2. READ executors (``execute_read``) — safe, auto-run, wrap the existing domain
     services and return JSON-serialisable dicts to feed back to the model.
  3. WRITE validators (``validate_write``) — validate the model's args with
     Pydantic and produce a human summary; they NEVER execute (writes become
     proposals, run only at confirm time by ``coach.execute``).

Write-tool args use HUMAN references (names / dates / titles), never ids — id
resolution happens later in ``coach.resolve``.
"""
from datetime import timedelta

from google.genai import types
from pydantic import BaseModel, Field, model_validator

from app.coach import balance, resolve
from app.exercises import service as exercises_service
from app.goals import service as goals_service
from app.muscles.constants import MUSCLE_GROUPS
from app.progress import service as progress_service
from app.workouts import service as workouts_service

# ──────────────────────────────────────────────────────────────────────────────
# Schema builders (compact wrappers over google-genai's OpenAPI-subset Schema)
# ──────────────────────────────────────────────────────────────────────────────
def _str(desc: str, enum: list[str] | None = None) -> types.Schema:
    # When constraining to a fixed set, the API expects format="enum" alongside it.
    fmt = "enum" if enum else None
    return types.Schema(type=types.Type.STRING, description=desc, enum=enum, format=fmt)


def _num(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.NUMBER, description=desc)


def _int(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.INTEGER, description=desc)


def _obj(properties: dict, required: list[str] | None = None) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT, properties=properties, required=required or []
    )


def _arr(items: types.Schema, desc: str) -> types.Schema:
    return types.Schema(type=types.Type.ARRAY, items=items, description=desc)


def _decl(name: str, desc: str, properties: dict, required: list[str] | None = None):
    # A no-argument tool declares no parameters at all (an empty OBJECT schema can
    # be rejected by the API), so pass parameters=None in that case.
    params = _obj(properties, required) if properties else None
    return types.FunctionDeclaration(name=name, description=desc, parameters=params)


_SET_SCHEMA = _obj(
    {
        "set_number": _int("1-based index of the set"),
        "weight_kg": _num("weight in kg; use 0 for bodyweight"),
        "reps": _int("repetitions performed"),
    },
    required=["set_number", "weight_kg", "reps"],
)

# ──────────────────────────────────────────────────────────────────────────────
# READ tools — safe, auto-executed, return data to the model
# ──────────────────────────────────────────────────────────────────────────────
async def _read_progress_overview(db, user_id, args) -> dict:
    ov = await progress_service.get_overview(db, user_id)
    return ov.model_dump(mode="json")


async def _read_recent_workouts(db, user_id, args) -> dict:
    if args.get("date"):
        d = resolve.parse_date_ref(args["date"])
        start_dt = d
        end_dt = (d + timedelta(days=1) - timedelta(microseconds=1)) if d else None
    else:
        s = resolve.parse_date_ref(args.get("start")) if args.get("start") else None
        e = resolve.parse_date_ref(args.get("end")) if args.get("end") else None
        start_dt = s
        end_dt = (e + timedelta(days=1) - timedelta(microseconds=1)) if e else None
    items = await workouts_service.list_workouts(db, user_id, start_dt, end_dt)
    return {"workouts": [i.model_dump(mode="json") for i in items]}


async def _read_workout(db, user_id, args) -> dict:
    try:
        wid, _ = await resolve.resolve_workout(
            db, user_id, args["workout_ref"], create=False
        )
    except resolve.NeedsClarification as e:
        return {"error": e.message}
    return (await workouts_service.get_workout(db, user_id, str(wid))).model_dump(mode="json")


async def _read_list_exercises(db, user_id, args) -> dict:
    items = await exercises_service.list_exercises(db, user_id, args.get("muscle"))
    return {"exercises": items}


async def _read_exercise(db, user_id, args) -> dict:
    try:
        eid, _ = await resolve.resolve_exercise(
            db, user_id, args["exercise_ref"], create=False
        )
    except resolve.NeedsClarification as e:
        return {"error": e.message}
    return await exercises_service.get_exercise(db, user_id, str(eid))


async def _read_exercise_progress(db, user_id, args) -> dict:
    try:
        eid, _ = await resolve.resolve_exercise(
            db, user_id, args["exercise_ref"], create=False
        )
    except resolve.NeedsClarification as e:
        return {"error": e.message}
    days = int(args.get("days") or 90)
    prog = await progress_service.get_exercise_progress(db, user_id, str(eid), days)
    return prog.model_dump(mode="json")


async def _read_muscle_balance(db, user_id, args) -> dict:
    ov = await progress_service.get_overview(db, user_id)
    return balance.audit_balance([m.model_dump() for m in ov.muscle_breakdown])


async def _read_list_goals(db, user_id, args) -> dict:
    goals = await goals_service.list_goals(db, user_id)
    return {"goals": [g.model_dump(mode="json") for g in goals]}


READ_EXECUTORS = {
    "get_progress_overview": _read_progress_overview,
    "get_recent_workouts": _read_recent_workouts,
    "get_workout": _read_workout,
    "list_exercises": _read_list_exercises,
    "get_exercise": _read_exercise,
    "get_exercise_progress": _read_exercise_progress,
    "get_muscle_balance": _read_muscle_balance,
    "list_goals": _read_list_goals,
}

_READ_DECLARATIONS = [
    _decl("get_progress_overview", "Overall training stats: totals, PRs this month, "
          "streak, and per-muscle volume breakdown.", {}),
    _decl("get_recent_workouts", "List the user's workouts (training sessions). "
          "Optionally filter by a single 'date' or a 'start'/'end' range.", {
              "date": _str("a single day: 'today', 'yesterday', or YYYY-MM-DD"),
              "start": _str("range start, YYYY-MM-DD or 'today'"),
              "end": _str("range end, YYYY-MM-DD or 'today'"),
          }),
    _decl("get_workout", "Get one workout (its muscle groups and the exercises "
          "logged under it).", {
              "workout_ref": _str("the day ('today'/YYYY-MM-DD) or the workout title"),
          }, required=["workout_ref"]),
    _decl("list_exercises", "List the user's exercises, optionally for one muscle.", {
        "muscle": _str("muscle group to filter by", enum=MUSCLE_GROUPS),
    }),
    _decl("get_exercise", "Get one exercise with its personal best and last session.", {
        "exercise_ref": _str("the exercise name, e.g. 'Bench Press'"),
    }, required=["exercise_ref"]),
    _decl("get_exercise_progress", "Weight-progression history (chart points + PR "
          "flags) for one exercise.", {
              "exercise_ref": _str("the exercise name"),
              "days": _int("how many days back to look (default 90)"),
          }, required=["exercise_ref"]),
    _decl("get_muscle_balance", "Deterministic push/pull/legs volume audit with any "
          "detected imbalances and which muscles to add.", {}),
    _decl("list_goals", "List the user's training goals.", {}),
]

# ──────────────────────────────────────────────────────────────────────────────
# WRITE tools — validated into proposals, NEVER executed here
# ──────────────────────────────────────────────────────────────────────────────
class _SetArg(BaseModel):
    set_number: int
    weight_kg: float = Field(..., ge=0)
    reps: int = Field(..., ge=1)


class CreateWorkoutArgs(BaseModel):
    date: str
    title: str = Field(..., min_length=1)


class AddMuscleGroupArgs(BaseModel):
    workout_ref: str
    muscle: str


class CreateExerciseArgs(BaseModel):
    muscle: str
    name: str = Field(..., min_length=2)
    emoji: str | None = None


class LogSetsArgs(BaseModel):
    exercise_ref: str
    sets: list[_SetArg] = Field(..., min_length=1)
    workout_ref: str = "today"
    muscle: str | None = None  # helps create the exercise if it's new
    notes: str | None = None


class MoveWorkoutArgs(BaseModel):
    workout_ref: str
    new_date: str


class UpdateWorkoutTitleArgs(BaseModel):
    workout_ref: str
    title: str = Field(..., min_length=1)


class DeleteWorkoutArgs(BaseModel):
    workout_ref: str


class CreateGoalArgs(BaseModel):
    target_value: float = Field(..., gt=0)
    target_date: str
    metric: str = "weight"
    exercise_ref: str | None = None


class UpdateGoalArgs(BaseModel):
    goal_id: str
    target_value: float | None = Field(default=None, gt=0)
    target_date: str | None = None
    status: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "UpdateGoalArgs":
        if self.target_value is None and self.target_date is None and self.status is None:
            raise ValueError("Provide at least one of target_value, target_date, status.")
        return self


def _sets_text(sets: list[_SetArg]) -> str:
    return ", ".join(f"{s.weight_kg:g}kg×{s.reps}" for s in sets)


# (Pydantic model, human-summary builder) per write tool.
WRITE_TOOLS: dict[str, tuple[type[BaseModel], object]] = {
    "create_workout": (
        CreateWorkoutArgs,
        lambda a: f"Create workout “{a.title}” on {a.date}.",
    ),
    "add_muscle_group": (
        AddMuscleGroupArgs,
        lambda a: f"Add the {a.muscle} muscle group to the {a.workout_ref} workout.",
    ),
    "create_exercise": (
        CreateExerciseArgs,
        lambda a: f"Create a new {a.muscle} exercise “{a.name}”.",
    ),
    "log_sets": (
        LogSetsArgs,
        lambda a: f"Log {a.exercise_ref} on {a.workout_ref}: {_sets_text(a.sets)}"
        + (f" (note: {a.notes})" if a.notes else "") + ".",
    ),
    "move_workout": (
        MoveWorkoutArgs,
        lambda a: f"Move the {a.workout_ref} workout to {a.new_date}.",
    ),
    "update_workout_title": (
        UpdateWorkoutTitleArgs,
        lambda a: f"Rename the {a.workout_ref} workout to “{a.title}”.",
    ),
    "delete_workout": (
        DeleteWorkoutArgs,
        lambda a: f"Delete the {a.workout_ref} workout (and its logged sets).",
    ),
    "create_goal": (
        CreateGoalArgs,
        lambda a: f"Set a goal: {a.target_value:g}kg"
        + (f" on {a.exercise_ref}" if a.exercise_ref else "") + f" by {a.target_date}.",
    ),
    "update_goal": (
        UpdateGoalArgs,
        lambda a: f"Update goal {a.goal_id}.",
    ),
}

_WRITE_DECLARATIONS = [
    _decl("create_workout", "Create a workout (training session) on a day.", {
        "date": _str("the day: 'today', 'tomorrow', or YYYY-MM-DD"),
        "title": _str("session title, e.g. 'Push', 'Pull', 'Legs'"),
    }, required=["date", "title"]),
    _decl("add_muscle_group", "Add a muscle group to a workout.", {
        "workout_ref": _str("the day ('today'/YYYY-MM-DD) or the workout title"),
        "muscle": _str("muscle group to add", enum=MUSCLE_GROUPS),
    }, required=["workout_ref", "muscle"]),
    _decl("create_exercise", "Create a new exercise in the user's library.", {
        "muscle": _str("muscle group", enum=MUSCLE_GROUPS),
        "name": _str("exercise name, e.g. 'Incline Dumbbell Press'"),
        "emoji": _str("optional emoji"),
    }, required=["muscle", "name"]),
    _decl("log_sets", "Log the sets the user performed for one exercise. This is how "
          "you record a workout from natural language.", {
              "workout_ref": _str("the day to log under: 'today', 'yesterday', or YYYY-MM-DD"),
              "exercise_ref": _str("the exercise name, e.g. 'Bench Press'"),
              "muscle": _str("the exercise's muscle group — include it if the "
                             "exercise might be new so it can be created", enum=MUSCLE_GROUPS),
              "sets": _arr(_SET_SCHEMA, "the sets performed, in order"),
              "notes": _str("optional note (RPE, how it felt, pain, form cue)"),
          }, required=["exercise_ref", "sets"]),
    _decl("move_workout", "Reschedule a workout to a different date (its logged sets "
          "move with it).", {
              "workout_ref": _str("the workout to move (day or title)"),
              "new_date": _str("the new day: 'tomorrow' or YYYY-MM-DD"),
          }, required=["workout_ref", "new_date"]),
    _decl("update_workout_title", "Rename a workout.", {
        "workout_ref": _str("the workout (day or current title)"),
        "title": _str("the new title"),
    }, required=["workout_ref", "title"]),
    _decl("delete_workout", "Delete a workout and the sets logged under it.", {
        "workout_ref": _str("the workout to delete (day or title)"),
    }, required=["workout_ref"]),
    _decl("create_goal", "Set a training goal (e.g. bench 80kg by August).", {
        "target_value": _num("the target value, e.g. 80 (kg)"),
        "target_date": _str("the deadline: YYYY-MM-DD"),
        "metric": _str("what the target measures (default 'weight')"),
        "exercise_ref": _str("the exercise this goal is about, by name"),
    }, required=["target_value", "target_date"]),
    _decl("update_goal", "Update or close an existing goal (use a goal id from "
          "list_goals).", {
              "goal_id": _str("the goal's id (from list_goals)"),
              "target_value": _num("new target value"),
              "target_date": _str("new deadline, YYYY-MM-DD"),
              "status": _str("new status", enum=["active", "achieved", "abandoned"]),
          }, required=["goal_id"]),
]

# ──────────────────────────────────────────────────────────────────────────────
# Public registry
# ──────────────────────────────────────────────────────────────────────────────
DECLARATIONS = _READ_DECLARATIONS + _WRITE_DECLARATIONS
READ_TOOL_NAMES = set(READ_EXECUTORS)
WRITE_TOOL_NAMES = set(WRITE_TOOLS)


async def execute_read(db, user_id, name: str, args: dict) -> dict:
    """Run a read tool and return its JSON-serialisable result."""
    return await READ_EXECUTORS[name](db, user_id, args or {})


def validate_write(name: str, raw_args: dict) -> tuple[dict, str]:
    """Validate a write tool's args. Returns ``(clean_args, human_summary)``; raises
    ``pydantic.ValidationError`` (or KeyError for an unknown tool) on bad input."""
    model, summarise = WRITE_TOOLS[name]
    parsed = model(**(raw_args or {}))
    return parsed.model_dump(exclude_none=True), summarise(parsed)
