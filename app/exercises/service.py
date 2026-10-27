"""Business logic for exercises, including derived stats (personal best,
last-session summary)."""
from app.exercises.models import COLLECTION, ExerciseDocument
from app.exercises.schemas import ExerciseCreate
from app.helpers.dates import now_utc
from app.helpers.exceptions import BadRequestError, NotFoundError
from app.helpers.objectid import parse_object_id
from app.muscles.constants import MUSCLE_GROUPS
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION


def _days_ago_label(dt) -> str:
    delta = now_utc() - dt
    if delta.days == 0:
        return "today"
    if delta.days == 1:
        return "yesterday"
    return f"{delta.days} days ago"


async def _personal_best(db, user_id, exercise_id):
    """Heaviest weight ever lifted for this exercise, or None."""
    pipeline = [
        {"$match": {"user_id": user_id, "exercise_id": exercise_id}},
        {"$unwind": "$sets"},
        {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
    ]
    result = await db[SESSIONS_COLLECTION].aggregate(pipeline).to_list(1)
    return result[0]["max"] if result else None


async def _session_stats(db, user_id) -> dict:
    """Map of exercise_id -> {personal_best, last_date, last_set_count} for the
    user, in a single aggregation over the sessions collection (replacing the
    previous two queries per exercise).

    personal_best is the heaviest set ever logged; last_date / last_set_count come
    from the most recent session (sessions sorted ascending so $last is newest).
    """
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$sort": {"date": 1}},
        {
            "$group": {
                "_id": "$exercise_id",
                "personal_best": {"$max": {"$max": "$sets.weight_kg"}},
                "last_date": {"$last": "$date"},
                "last_set_count": {"$last": {"$size": "$sets"}},
            }
        },
    ]
    return {
        r["_id"]: r
        for r in await db[SESSIONS_COLLECTION].aggregate(pipeline).to_list(length=None)
    }


async def list_exercises(db, user_id, muscle: str | None = None) -> list[dict]:
    query = {"user_id": user_id}
    if muscle:
        query["muscle"] = muscle.lower()

    exercises = await db[COLLECTION].find(query).sort("created_at", 1).to_list(200)
    stats = await _session_stats(db, user_id)

    result = []
    for ex in exercises:
        ex_id = ex["_id"]
        st = stats.get(ex_id)

        personal_best = st["personal_best"] if st else None
        last_session_summary = None
        set_count = None
        if st and st["last_date"] is not None:
            set_count = st["last_set_count"]
            label = _days_ago_label(st["last_date"])
            last_session_summary = f"{set_count} set{'s' if set_count != 1 else ''} · {label}"

        result.append(
            {
                "id": str(ex_id),
                "muscle": ex["muscle"],
                "name": ex["name"],
                "emoji": ex.get("emoji", "🏋️"),
                "image_url": ex.get("image_url"),
                "personal_best": personal_best,
                "last_session_summary": last_session_summary,
                "set_count": set_count,
            }
        )

    return result


async def get_exercise(db, user_id, exercise_id: str) -> dict:
    oid = parse_object_id(exercise_id, "exercise id")
    ex = await db[COLLECTION].find_one({"_id": oid, "user_id": user_id})
    if not ex:
        raise NotFoundError("Exercise not found")

    personal_best = await _personal_best(db, user_id, oid)
    last_session = await db[SESSIONS_COLLECTION].find_one(
        {"user_id": user_id, "exercise_id": oid}, sort=[("date", -1)]
    )
    last_session_data = None
    if last_session:
        last_session_data = {
            "id": str(last_session["_id"]),
            "notes": last_session.get("notes"),
            "sets": last_session["sets"],
        }

    return {
        "id": str(ex["_id"]),
        "muscle": ex["muscle"],
        "name": ex["name"],
        "emoji": ex.get("emoji", "🏋️"),
        "image_url": ex.get("image_url"),
        "personal_best": personal_best,
        "last_session": last_session_data,
    }


async def create_exercise(db, user_id, body: ExerciseCreate) -> dict:
    if body.muscle.lower() not in MUSCLE_GROUPS:
        raise BadRequestError(f"Invalid muscle. Choose from: {MUSCLE_GROUPS}")

    doc = ExerciseDocument(
        user_id=user_id,
        muscle=body.muscle.lower(),
        name=body.name.strip(),
        emoji=body.emoji or "🏋️",
        image_url=body.image_url,
    ).model_dump()
    result = await db[COLLECTION].insert_one(doc)

    return {
        "id": str(result.inserted_id),
        "muscle": doc["muscle"],
        "name": doc["name"],
        "emoji": doc["emoji"],
        "image_url": doc["image_url"],
        "personal_best": None,
        "last_session_summary": None,
        "set_count": None,
    }


async def delete_exercise(db, user_id, exercise_id: str) -> None:
    oid = parse_object_id(exercise_id, "exercise id")
    result = await db[COLLECTION].delete_one({"_id": oid, "user_id": user_id})
    if result.deleted_count == 0:
        raise NotFoundError("Exercise not found")

    # Cascade-delete every session logged for this exercise.
    await db[SESSIONS_COLLECTION].delete_many({"user_id": user_id, "exercise_id": oid})
