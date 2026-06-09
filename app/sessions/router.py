"""Session endpoints: CRUD under /sessions."""
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.helpers.filters import Pagination, pagination_params
from app.sessions import service
from app.sessions.schemas import SessionCreate, SessionResponse, SessionUpdate

router = APIRouter()


@router.get("", response_model=list[SessionResponse])
async def get_sessions(
    exercise_id: str | None = None,
    workout_id: str | None = None,
    page: Pagination = Depends(pagination_params),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.list_sessions(
        db, current_user["_id"], page, exercise_id, workout_id
    )


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: SessionCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.create_session(db, current_user["_id"], body)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.get_session(db, current_user["_id"], session_id)


@router.put("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    body: SessionUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.update_session(db, current_user["_id"], session_id, body)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    await service.delete_session(db, current_user["_id"], session_id)
