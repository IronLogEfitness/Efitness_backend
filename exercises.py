from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime, timedelta
from bson import ObjectId
from typing import List, Optional
from schema import ExerciseCreate
from security import get_current_user
from database import get_db

router = APIRouter()


def _days_ago_label(dt: datetime) -> str:
    delta = datetime.utcnow() - dt
    if delta.days == 0:
        return "today"
    if delta.days == 1:
        return "yesterday"
    return f"{delta.days} days ago"


# ─────────────────────────────────────────────────────────
#  GET /exercises?muscle=chest
# ─────────────────────────────────────────────────────────
@router.get("")
async def list_exercises(
    muscle: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    uid = current_user["_id"]
    query = {"user_id": uid}
    if muscle:
        query["muscle"] = muscle.lower()

    exercises = await db["exercises"].find(query).sort("created_at", 1).to_list(200)
    result = []

    for ex in exercises:
        ex_id = ex["_id"]

        # Personal best (max weight ever)
        pb_pipeline = [
            {"$match": {"user_id": uid, "exercise_id": ex_id}},
            {"$unwind": "$sets"},
            {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
        ]
        pb_result = await db["sessions"].aggregate(pb_pipeline).to_list(1)
        personal_best = pb_result[0]["max"] if pb_result else None

        # Last session summary
        last_session = await db["sessions"].find_one(
            {"user_id": uid, "exercise_id": ex_id},
            sort=[("date", -1)],
        )
        last_session_summary = None
        set_count = None
        if last_session:
            set_count = len(last_session["sets"])
            label = _days_ago_label(last_session["date"])
            last_session_summary = f"{set_count} set{'s' if set_count != 1 else ''} · {label}"

        result.append({
            "id":                   str(ex_id),
            "muscle":               ex["muscle"],
            "name":                 ex["name"],
            "emoji":                ex.get("emoji", "🏋️"),
            "image_url":            ex.get("image_url"),
            "personal_best":        personal_best,
            "last_session_summary": last_session_summary,
            "set_count":            set_count,
        })

    return result


# ─────────────────────────────────────────────────────────
#  GET /exercises/{id}
# ─────────────────────────────────────────────────────────
@router.get("/{exercise_id}")
async def get_exercise(
    exercise_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    uid = current_user["_id"]
    try:
        oid = ObjectId(exercise_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid exercise id")

    ex = await db["exercises"].find_one({"_id": oid, "user_id": uid})
    if not ex:
        raise HTTPException(status_code=404, detail="Exercise not found")

    # Personal best
    pb_pipeline = [
        {"$match": {"user_id": uid, "exercise_id": oid}},
        {"$unwind": "$sets"},
        {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
    ]
    pb_result = await db["sessions"].aggregate(pb_pipeline).to_list(1)
    personal_best = pb_result[0]["max"] if pb_result else None

    # Last session with sets
    last_session = await db["sessions"].find_one(
        {"user_id": uid, "exercise_id": oid},
        sort=[("date", -1)],
    )
    last_session_data = None
    if last_session:
        last_session_data = {
            "id":    str(last_session["_id"]),
            "notes": last_session.get("notes"),
            "sets":  last_session["sets"],
        }

    return {
        "id":            str(ex["_id"]),
        "muscle":        ex["muscle"],
        "name":          ex["name"],
        "emoji":         ex.get("emoji", "🏋️"),
        "image_url":     ex.get("image_url"),
        "personal_best": personal_best,
        "last_session":  last_session_data,
    }


# ─────────────────────────────────────────────────────────
#  POST /exercises
# ─────────────────────────────────────────────────────────
@router.post("", status_code=201)
async def create_exercise(
    body: ExerciseCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    uid = current_user["_id"]

    from schema import MUSCLE_GROUPS
    if body.muscle.lower() not in MUSCLE_GROUPS:
        raise HTTPException(status_code=400, detail=f"Invalid muscle. Choose from: {MUSCLE_GROUPS}")

    doc = {
        "user_id":    uid,
        "muscle":     body.muscle.lower(),
        "name":       body.name.strip(),
        "emoji":      body.emoji or "🏋️",
        "image_url":  body.image_url,
        "created_at": datetime.utcnow(),
    }
    result = await db["exercises"].insert_one(doc)

    return {
        "id":                   str(result.inserted_id),
        "muscle":               doc["muscle"],
        "name":                 doc["name"],
        "emoji":                doc["emoji"],
        "image_url":            doc["image_url"],
        "personal_best":        None,
        "last_session_summary": None,
        "set_count":            None,
    }


# ─────────────────────────────────────────────────────────
#  DELETE /exercises/{id}  (also removes all sessions)
# ─────────────────────────────────────────────────────────
@router.delete("/{exercise_id}", status_code=204)
async def delete_exercise(
    exercise_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    uid = current_user["_id"]
    try:
        oid = ObjectId(exercise_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid exercise id")

    result = await db["exercises"].delete_one({"_id": oid, "user_id": uid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Exercise not found")

    # Cascade-delete all sessions for this exercise
    await db["sessions"].delete_many({"user_id": uid, "exercise_id": oid})
