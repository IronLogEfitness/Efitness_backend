"""Exercise endpoints: CRUD under /exercises."""
from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.exercises import service
from app.exercises.schemas import ExerciseCreate, ExerciseDetail, ExerciseListItem

router = APIRouter()


@router.get("", response_model=list[ExerciseListItem])
async def list_exercises(
    muscle: str | None = Query(None),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.list_exercises(db, current_user["_id"], muscle)


@router.get("/{exercise_id}", response_model=ExerciseDetail)
async def get_exercise(
    exercise_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.get_exercise(db, current_user["_id"], exercise_id)


@router.post("", response_model=ExerciseListItem, status_code=201)
async def create_exercise(
    body: ExerciseCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.create_exercise(db, current_user["_id"], body)


@router.delete("/{exercise_id}", status_code=204)
async def delete_exercise(
    exercise_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    await service.delete_exercise(db, current_user["_id"], exercise_id)
