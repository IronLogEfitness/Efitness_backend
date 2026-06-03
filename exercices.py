from fastapi import APIRouter, Depends
from security import get_current_user
from database import get_db
from schema import MUSCLE_GROUPS

router = APIRouter()

# ─────────────────────────────────────────────────────────
#  GET /muscles
#  Returns all muscle groups with how many exercises
#  the user has for each one.
#
#  Response example:
#  [
#    { "muscle": "chest",   "exercise_count": 3, "last_trained": "2025-05-21T..." },
#    { "muscle": "back",    "exercise_count": 2, "last_trained": "2025-05-19T..." },
#    { "muscle": "biceps",  "exercise_count": 2, "last_trained": "2025-05-19T..." },
#    { "muscle": "legs",    "exercise_count": 0, "last_trained": null },
#    ...
#  ]
# ─────────────────────────────────────────────────────────
@router.get("")
async def get_muscles(current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = current_user["_id"]
    result = []

    for muscle in MUSCLE_GROUPS:
        # Count exercises for this muscle
        count = await db["exercises"].count_documents({
            "user_id": user_id,
            "muscle": muscle
        })

        # Find the most recent session for any exercise in this muscle
        pipeline = [
            {"$match": {"user_id": user_id, "muscle": muscle}},
            {"$lookup": {
                "from": "sessions",
                "localField": "_id",
                "foreignField": "exercise_id",
                "as": "sessions"
            }},
            {"$unwind": {"path": "$sessions", "preserveNullAndEmptyArrays": True}},
            {"$sort": {"sessions.date": -1}},
            {"$limit": 1},
            {"$project": {"last_trained": "$sessions.date"}}
        ]
        cursor = db["exercises"].aggregate(pipeline)
        docs = await cursor.to_list(1)
        last_trained = docs[0].get("last_trained") if docs else None

        result.append({
            "muscle":          muscle,
            "exercise_count":  count,
            "last_trained":    last_trained,
        })

    return result