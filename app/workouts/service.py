"""Business logic for training sessions (workouts).

A workout is the day-level container; its logged sets live in the `sessions`
collection and link back via `workout_id`. Every query here is scoped to
`user_id` (from the verified JWT), never from the request body.
"""
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
    WorkoutDetail,
    WorkoutListItem,
    WorkoutUpdate,
)


def _day_to_utc_midnight(day) -> datetime:
    """Normalise a calendar date to midnight UTC, the canonical stored value."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


async def _exercise_count(db, user_id, muscle_groups: list[str]) -> int:
    if not muscle_groups:
        return 0
    return await db[EXERCISES_COLLECTION].count_documents(
        {"user_id": user_id, "muscle": {"$in": muscle_groups}}
    )


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
        _list_item(d, await _exercise_count(db, user_id, d.get("muscle_groups", [])))
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


async def _exercises_block(db, user_id, workout_id, muscle: str) -> list[ExerciseInWorkout]:
    """Exercises of `muscle`, each annotated with what was logged in this workout."""
    exercises = await db[EXERCISES_COLLECTION].find(
        {"user_id": user_id, "muscle": muscle}
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
    blocks = [
        MuscleGroupBlock(
            muscle=muscle,
            exercises=await _exercises_block(db, user_id, doc["_id"], muscle),
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


async def delete_workout(db, user_id, workout_id: str) -> None:
    oid = parse_object_id(workout_id, "workout id")
    result = await db[COLLECTION].delete_one({"_id": oid, "user_id": user_id})
    if result.deleted_count == 0:
        raise NotFoundError("Workout not found")

    # Cascade-delete the set-logs logged under this workout (mirrors how deleting
    # an exercise cascades its sessions in app.exercises.service).
    await db[SESSIONS_COLLECTION].delete_many({"user_id": user_id, "workout_id": oid})
