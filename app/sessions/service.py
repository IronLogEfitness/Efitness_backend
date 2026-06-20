"""Business logic for logging and editing training sessions."""
from app.coach.prs import detect_pr
from app.coach.schemas import PRBadge
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.helpers.exceptions import BadRequestError, NotFoundError
from app.helpers.filters import Pagination
from app.helpers.objectid import parse_object_id
from app.sessions.models import COLLECTION, SessionDocument
from app.sessions.schemas import SessionCreate, SessionResponse, SessionUpdate
from app.workouts.models import COLLECTION as WORKOUTS_COLLECTION


async def _personal_best(db, user_id, exercise_id) -> float | None:
    """Heaviest weight ever logged for this exercise (None if no history)."""
    agg = await db[COLLECTION].aggregate(
        [
            {"$match": {"user_id": user_id, "exercise_id": exercise_id}},
            {"$unwind": "$sets"},
            {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
        ]
    ).to_list(1)
    return agg[0]["max"] if agg else None


def _to_response(doc: dict) -> SessionResponse:
    workout_id = doc.get("workout_id")
    return SessionResponse(
        id=str(doc["_id"]),
        exercise_id=str(doc["exercise_id"]),
        workout_id=str(workout_id) if workout_id else None,
        date=doc["date"],
        sets=doc["sets"],
        notes=doc.get("notes"),
        created_at=doc["created_at"],
    )


async def list_sessions(
    db, user_id, page: Pagination, exercise_id: str | None = None,
    workout_id: str | None = None,
) -> list[SessionResponse]:
    query = {"user_id": user_id}
    if exercise_id:
        query["exercise_id"] = parse_object_id(exercise_id, "exercise id")
    if workout_id:
        query["workout_id"] = parse_object_id(workout_id, "workout id")

    cursor = (
        db[COLLECTION]
        .find(query)
        .sort("date", -1)
        .skip(page.skip)
        .limit(page.limit)
    )
    docs = await cursor.to_list(length=page.limit)
    return [_to_response(d) for d in docs]


async def create_session(db, user_id, body: SessionCreate) -> SessionResponse:
    exercise_oid = parse_object_id(body.exercise_id, "exercise id")

    # The exercise must exist and belong to this user.
    exercise = await db[EXERCISES_COLLECTION].find_one(
        {"_id": exercise_oid, "user_id": user_id}
    )
    if not exercise:
        raise NotFoundError("Exercise not found")

    # When logged from the agenda flow, tie the set-log to its training session.
    workout_oid = None
    if body.workout_id:
        workout_oid = parse_object_id(body.workout_id, "workout id")
        workout = await db[WORKOUTS_COLLECTION].find_one(
            {"_id": workout_oid, "user_id": user_id}
        )
        if not workout:
            raise NotFoundError("Workout not found")

    # Snapshot the prior best BEFORE inserting so PR detection is correct.
    prev_best = await _personal_best(db, user_id, exercise_oid)

    doc = SessionDocument(
        user_id=user_id,
        exercise_id=exercise_oid,
        workout_id=workout_oid,
        date=body.date or now_utc(),
        sets=[s.model_dump() for s in body.sets],
        notes=body.notes,
    ).model_dump()
    result = await db[COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id

    # Logging a set under a workout makes that exercise part of the workout, so it
    # shows up in the workout's muscle block (membership is per-workout). No-op when
    # logged standalone (no workout_id).
    if workout_oid is not None:
        await db[WORKOUTS_COLLECTION].update_one(
            {"_id": workout_oid, "user_id": user_id},
            {"$addToSet": {"exercise_ids": exercise_oid}},
        )

    response = _to_response(doc)
    badge = detect_pr([s.model_dump() for s in body.sets], prev_best)
    if badge:
        response.pr = PRBadge(**badge)
    return response


async def get_session(db, user_id, session_id: str) -> SessionResponse:
    oid = parse_object_id(session_id, "session id")
    doc = await db[COLLECTION].find_one({"_id": oid, "user_id": user_id})
    if not doc:
        raise NotFoundError("Session not found")
    return _to_response(doc)


async def update_session(
    db, user_id, session_id: str, body: SessionUpdate
) -> SessionResponse:
    oid = parse_object_id(session_id, "session id")

    update_data: dict = {}
    if body.sets is not None:
        update_data["sets"] = [s.model_dump() for s in body.sets]
    if body.notes is not None:
        update_data["notes"] = body.notes
    if not update_data:
        raise BadRequestError("Nothing to update")

    doc = await db[COLLECTION].find_one_and_update(
        {"_id": oid, "user_id": user_id},
        {"$set": update_data},
        return_document=True,
    )
    if not doc:
        raise NotFoundError("Session not found")
    return _to_response(doc)


async def delete_session(db, user_id, session_id: str) -> None:
    oid = parse_object_id(session_id, "session id")
    result = await db[COLLECTION].delete_one({"_id": oid, "user_id": user_id})
    if result.deleted_count == 0:
        raise NotFoundError("Session not found")
