from fastapi import APIRouter, HTTPException, Depends, Query
from datetime import datetime
from bson import ObjectId
from typing import List, Optional
from schema import SessionCreate, SessionUpdate, SessionResponse
from security import get_current_user
from database import get_db

router = APIRouter()

def _fmt(doc) -> SessionResponse:
    return SessionResponse(
        id=str(doc["_id"]),
        exercise_id=str(doc["exercise_id"]),
        date=doc["date"],
        sets=doc["sets"],
        notes=doc.get("notes"),
        created_at=doc["created_at"],
    )

# ─────────────────────────────────────────────────────────
#  GET /sessions?exercise_id=xxx&limit=20&skip=0
#  Get sessions for the current user.
#  Filter by exercise or get all, paginated.
# ─────────────────────────────────────────────────────────
@router.get("", response_model=List[SessionResponse])
async def get_sessions(
    exercise_id: Optional[str] = None,
    limit:       int = Query(default=20, le=100),
    skip:        int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    query = {"user_id": current_user["_id"]}
    if exercise_id:
        query["exercise_id"] = ObjectId(exercise_id)

    cursor = db["sessions"].find(query).sort("date", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [_fmt(d) for d in docs]


# ─────────────────────────────────────────────────────────
#  POST /sessions
#  Log a new training session.
#
#  Body: { exercise_id, date?, sets: [{set_number, weight_kg, reps}], notes? }
# ─────────────────────────────────────────────────────────
@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: SessionCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    # Verify exercise belongs to this user
    exercise = await db["exercises"].find_one({
        "_id":     ObjectId(body.exercise_id),
        "user_id": current_user["_id"]
    })
    if not exercise:
        raise HTTPException(status_code=404, detail="Exercise not found")

    doc = {
        "user_id":     current_user["_id"],
        "exercise_id": ObjectId(body.exercise_id),
        "date":        body.date or datetime.utcnow(),
        "sets":        [s.dict() for s in body.sets],
        "notes":       body.notes,
        "created_at":  datetime.utcnow(),
    }
    result = await db["sessions"].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _fmt(doc)


# ─────────────────────────────────────────────────────────
#  GET /sessions/{session_id}
#  Get a single session in full detail.
# ─────────────────────────────────────────────────────────
@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    doc = await db["sessions"].find_one({
        "_id":     ObjectId(session_id),
        "user_id": current_user["_id"]
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found")
    return _fmt(doc)


# ─────────────────────────────────────────────────────────
#  PUT /sessions/{session_id}
#  Edit sets or notes of an existing session.
# ─────────────────────────────────────────────────────────
@router.put("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    body: SessionUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    update_data = {}
    if body.sets is not None:
        update_data["sets"] = [s.dict() for s in body.sets]
    if body.notes is not None:
        update_data["notes"] = body.notes

    if not update_data:
        raise HTTPException(status_code=400, detail="Nothing to update")

    result = await db["sessions"].find_one_and_update(
        {"_id": ObjectId(session_id), "user_id": current_user["_id"]},
        {"$set": update_data},
        return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    return _fmt(result)


# ─────────────────────────────────────────────────────────
#  DELETE /sessions/{session_id}
# ─────────────────────────────────────────────────────────
@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    result = await db["sessions"].delete_one({
        "_id":     ObjectId(session_id),
        "user_id": current_user["_id"]
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Session not found")