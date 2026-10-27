"""Read-only aggregation: how many exercises and the last-trained date per muscle."""
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.muscles.constants import MUSCLE_GROUPS
from app.muscles.schemas import MuscleSummary
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION


async def list_muscles(db, user_id) -> list[MuscleSummary]:
    # One aggregation for every muscle's exercise count + last-trained date
    # (previously a count query plus a lookup pipeline per muscle group): join
    # exercises -> their sessions and group by muscle. Exercises with no sessions
    # contribute a null date that $max ignores, so an untrained muscle is None.
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$lookup": {
                "from": SESSIONS_COLLECTION,
                "localField": "_id",
                "foreignField": "exercise_id",
                "as": "sessions",
            }
        },
        {
            "$group": {
                "_id": "$muscle",
                "exercise_count": {"$sum": 1},
                "last_trained": {"$max": {"$max": "$sessions.date"}},
            }
        },
    ]
    rows = {
        r["_id"]: r
        for r in await db[EXERCISES_COLLECTION].aggregate(pipeline).to_list(length=None)
    }

    # Keep every muscle group, in MUSCLE_GROUPS order, zeros/None for untrained ones.
    return [
        MuscleSummary(
            muscle=muscle,
            exercise_count=rows[muscle]["exercise_count"] if muscle in rows else 0,
            last_trained=rows[muscle]["last_trained"] if muscle in rows else None,
        )
        for muscle in MUSCLE_GROUPS
    ]
