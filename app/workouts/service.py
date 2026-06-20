"""Business logic for training sessions (workouts).

A workout is the day-level container; its logged sets live in the `sessions`
collection and link back via `workout_id`. Every query here is scoped to
`user_id` (from the verified JWT), never from the request body.
"""
import re
from datetime import datetime, time, timezone

from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.exceptions import BadRequestError, NotFoundError
from app.helpers.objectid import parse_object_id
from app.muscles.constants import MUSCLE_GROUPS
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION
from app.workouts.models import COLLECTION, WorkoutDocument
from app.workouts.schemas import (
    ExerciseInWorkout,
    MuscleGroupBlock,
    WorkoutCreate,
    WorkoutExerciseAdd,
    WorkoutDetail,
    WorkoutListItem,
    WorkoutUpdate,
)


async def _member_exercise_ids(db, user_id, workout_doc: dict) -> list:
    """Catalog exercise ids that belong to this workout.

    The union of the workout's explicit membership (`exercise_ids`) and any exercise
    that already has sets logged under this workout. The union keeps legacy workouts
    (created before the `exercise_ids` field existed) showing their logged exercises,
    and guarantees logged data can never be hidden by a stale membership list.
    """
    logged = await db[SESSIONS_COLLECTION].distinct(
        "exercise_id", {"user_id": user_id, "workout_id": workout_doc["_id"]}
    )
    seen, members = set(), []
    for oid in [*workout_doc.get("exercise_ids", []), *logged]:
        if oid not in seen:
            seen.add(oid)
            members.append(oid)
    return members


def _day_to_utc_midnight(day) -> datetime:
    """Normalise a calendar date to midnight UTC, the canonical stored value."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


async def _exercise_count(db, user_id, workout_doc: dict) -> int:
    """How many exercises belong to this workout (not the whole muscle catalog)."""
    return len(await _member_exercise_ids(db, user_id, workout_doc))


def _list_item(doc: dict, exercise_count: int) -> WorkoutListItem:
    return WorkoutListItem(
        id=str(doc["_id"]),
        date=doc["date"],
        title=doc["title"],
        muscle_groups=doc.get("muscle_groups", []),
        exercise_count=exercise_count,
    )


async def list_workouts(
    db, user_id, start: datetime | None, end: datetime | None
) -> list[WorkoutListItem]:
    query: dict = {"user_id": user_id}
    if start is not None or end is not None:
        date_filter: dict = {}
        if start is not None:
            date_filter["$gte"] = start
        if end is not None:
            date_filter["$lte"] = end
        query["date"] = date_filter

    docs = await db[COLLECTION].find(query).sort("date", 1).to_list(length=500)
    return [
        _list_item(d, await _exercise_count(db, user_id, d))
        for d in docs
    ]


async def create_workout(db, user_id, body: WorkoutCreate) -> WorkoutListItem:
    doc = WorkoutDocument(
        user_id=user_id,
        date=_day_to_utc_midnight(body.date),
        title=body.title.strip(),
        muscle_groups=[],
    ).model_dump()
    result = await db[COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _list_item(doc, 0)


async def _require_workout(db, user_id, workout_id: str) -> dict:
    oid = parse_object_id(workout_id, "workout id")
    doc = await db[COLLECTION].find_one({"_id": oid, "user_id": user_id})
    if not doc:
        raise NotFoundError("Workout not found")
    return doc


async def _exercises_block(
    db, user_id, workout_id, member_ids: list, muscle: str
) -> list[ExerciseInWorkout]:
    """This workout's exercises for `muscle`, each annotated with what was logged here.

    Scoped to `member_ids` (the exercises that belong to this workout) — NOT the whole
    per-muscle catalog — so a session only ever shows the exercises added to it.
    """
    if not member_ids:
        return []

    exercises = await db[EXERCISES_COLLECTION].find(
        {"_id": {"$in": member_ids}, "user_id": user_id, "muscle": muscle}
    ).sort("created_at", 1).to_list(200)

    block: list[ExerciseInWorkout] = []
    for ex in exercises:
        logs = await db[SESSIONS_COLLECTION].find(
            {"user_id": user_id, "exercise_id": ex["_id"], "workout_id": workout_id}
        ).sort("date", -1).to_list(50)

        set_count = sum(len(log["sets"]) for log in logs)
        last_summary = None
        if logs:
            latest = logs[0]
            last_summary = ", ".join(
                f"{st['weight_kg']}kg×{st['reps']}" for st in latest["sets"]
            )

        block.append(
            ExerciseInWorkout(
                id=str(ex["_id"]),
                name=ex["name"],
                emoji=ex.get("emoji", "🏋️"),
                muscle=ex["muscle"],
                logged_set_count=set_count,
                last_summary=last_summary,
                image_url=ex.get("image_url"),
            )
        )
    return block


async def get_workout(db, user_id, workout_id: str) -> WorkoutDetail:
    doc = await _require_workout(db, user_id, workout_id)
    member_ids = await _member_exercise_ids(db, user_id, doc)
    blocks = [
        MuscleGroupBlock(
            muscle=muscle,
            exercises=await _exercises_block(db, user_id, doc["_id"], member_ids, muscle),
        )
        for muscle in doc.get("muscle_groups", [])
    ]
    return WorkoutDetail(
        id=str(doc["_id"]),
        date=doc["date"],
        title=doc["title"],
        muscle_groups=blocks,
    )


async def update_workout(db, user_id, workout_id: str, body: WorkoutUpdate) -> WorkoutDetail:
    await _require_workout(db, user_id, workout_id)

    update: dict = {}
    if body.title is not None:
        update["title"] = body.title.strip()
    if body.date is not None:
        # Move the workout to another day. Logged sets are untouched — they link by
        # workout_id, so only the workout's own `date` changes.
        update["date"] = _day_to_utc_midnight(body.date)
    if not update:
        raise BadRequestError("Nothing to update")

    oid = parse_object_id(workout_id, "workout id")
    await db[COLLECTION].update_one({"_id": oid, "user_id": user_id}, {"$set": update})
    return await get_workout(db, user_id, workout_id)


async def add_muscle_group(db, user_id, workout_id: str, muscle: str) -> WorkoutDetail:
    muscle = muscle.lower()
    if muscle not in MUSCLE_GROUPS:
        raise BadRequestError(f"Invalid muscle. Choose from: {MUSCLE_GROUPS}")

    oid = parse_object_id(workout_id, "workout id")
    result = await db[COLLECTION].update_one(
        {"_id": oid, "user_id": user_id}, {"$addToSet": {"muscle_groups": muscle}}
    )
    if result.matched_count == 0:
        raise NotFoundError("Workout not found")
    return await get_workout(db, user_id, workout_id)


async def remove_muscle_group(db, user_id, workout_id: str, muscle: str) -> WorkoutDetail:
    oid = parse_object_id(workout_id, "workout id")
    result = await db[COLLECTION].update_one(
        {"_id": oid, "user_id": user_id}, {"$pull": {"muscle_groups": muscle.lower()}}
    )
    if result.matched_count == 0:
        raise NotFoundError("Workout not found")
    return await get_workout(db, user_id, workout_id)


async def add_workout_exercise(
    db, user_id, workout_id: str, body: WorkoutExerciseAdd
) -> WorkoutDetail:
    """Add an exercise to this workout's muscle block.

    Finds-or-creates the exercise in the shared catalog by (muscle, name) — a re-used
    name keeps its existing id, so its personal-best / progress / coach history carries
    over — then links it to THIS workout only. Membership is per-workout, so other
    sessions are unaffected.
    """
    muscle = body.muscle.lower()
    if muscle not in MUSCLE_GROUPS:
        raise BadRequestError(f"Invalid muscle. Choose from: {MUSCLE_GROUPS}")

    name = body.name.strip()
    if len(name) < 2:
        raise BadRequestError("Exercise name is too short.")

    oid = parse_object_id(workout_id, "workout id")
    workout = await db[COLLECTION].find_one({"_id": oid, "user_id": user_id})
    if not workout:
        raise NotFoundError("Workout not found")

    # Reuse an existing catalog exercise (case-insensitive name match within the
    # muscle) so tracking history is preserved; otherwise create a fresh one.
    existing = await db[EXERCISES_COLLECTION].find_one(
        {
            "user_id": user_id,
            "muscle": muscle,
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
        }
    )
    if existing:
        exercise_oid = existing["_id"]
    else:
        from app.exercises.schemas import ExerciseCreate
        from app.exercises.service import create_exercise

        created = await create_exercise(
            db,
            user_id,
            ExerciseCreate(
                muscle=muscle,
                name=name,
                emoji=body.emoji or "🏋️",
                image_url=body.image_url,
            ),
        )
        exercise_oid = parse_object_id(created["id"], "exercise id")

    # Ensure the muscle is on the workout and the exercise is a member of it.
    await db[COLLECTION].update_one(
        {"_id": oid, "user_id": user_id},
        {"$addToSet": {"muscle_groups": muscle, "exercise_ids": exercise_oid}},
    )
    return await get_workout(db, user_id, workout_id)


async def remove_workout_exercise(
    db, user_id, workout_id: str, exercise_id: str
) -> WorkoutDetail:
    """Remove an exercise from THIS workout only.

    Unlinks it from the workout's membership and deletes the sets logged for it under
    this workout. The catalog exercise and its history in *other* sessions are left
    intact (unlike the global DELETE /exercises/{id}, which wipes all of it).
    """
    oid = parse_object_id(workout_id, "workout id")
    exercise_oid = parse_object_id(exercise_id, "exercise id")

    result = await db[COLLECTION].update_one(
        {"_id": oid, "user_id": user_id},
        {"$pull": {"exercise_ids": exercise_oid}},
    )
    if result.matched_count == 0:
        raise NotFoundError("Workout not found")

    await db[SESSIONS_COLLECTION].delete_many(
        {"user_id": user_id, "exercise_id": exercise_oid, "workout_id": oid}
    )
    return await get_workout(db, user_id, workout_id)


async def delete_workout(db, user_id, workout_id: str) -> None:
    oid = parse_object_id(workout_id, "workout id")
    result = await db[COLLECTION].delete_one({"_id": oid, "user_id": user_id})
    if result.deleted_count == 0:
        raise NotFoundError("Workout not found")

    # Cascade-delete the set-logs logged under this workout (mirrors how deleting
    # an exercise cascades its sessions in app.exercises.service).
    await db[SESSIONS_COLLECTION].delete_many({"user_id": user_id, "workout_id": oid})
