"""Read-only aggregation: how many exercises and the last-trained date per muscle."""
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.muscles.constants import MUSCLE_GROUPS
from app.muscles.schemas import MuscleSummary
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION


async def list_muscles(db, user_id) -> list[MuscleSummary]:
    result: list[MuscleSummary] = []

    for muscle in MUSCLE_GROUPS:
        count = await db[EXERCISES_COLLECTION].count_documents(
            {"user_id": user_id, "muscle": muscle}
        )

        # Most recent session date across any exercise in this muscle group.
        pipeline = [
            {"$match": {"user_id": user_id, "muscle": muscle}},
            {
                "$lookup": {
                    "from": SESSIONS_COLLECTION,
                    "localField": "_id",
                    "foreignField": "exercise_id",
                    "as": "sessions",
                }
            },
            {"$unwind": {"path": "$sessions", "preserveNullAndEmptyArrays": True}},
            {"$sort": {"sessions.date": -1}},
            {"$limit": 1},
            {"$project": {"last_trained": "$sessions.date"}},
        ]
        docs = await db[EXERCISES_COLLECTION].aggregate(pipeline).to_list(1)
        last_trained = docs[0].get("last_trained") if docs else None

        result.append(
            MuscleSummary(
                muscle=muscle,
                exercise_count=count,
                last_trained=last_trained,
            )
        )

    return result
