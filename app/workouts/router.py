"""Workout (training-session) endpoints: CRUD under /workouts."""
from datetime import date as date_type
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.workouts import service
from app.workouts.schemas import (
    MuscleGroupAdd,
    WorkoutCreate,
    WorkoutDetail,
    WorkoutExerciseAdd,
    WorkoutListItem,
    WorkoutUpdate,
)

router = APIRouter()


@router.get("", response_model=list[WorkoutListItem])
async def list_workouts(
    start: date_type | None = Query(None, description="Range start (inclusive), YYYY-MM-DD"),
    end: date_type | None = Query(None, description="Range end (inclusive), YYYY-MM-DD"),
    date: date_type | None = Query(None, description="Single day, YYYY-MM-DD"),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    # A single `date` is shorthand for the [day 00:00, day 23:59:59] range.
    if date is not None:
        start = end = date
    start_dt = (
        datetime.combine(start, time.min, tzinfo=timezone.utc) if start else None
    )
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc) if end else None
    return await service.list_workouts(db, current_user["_id"], start_dt, end_dt)


@router.post("", response_model=WorkoutListItem, status_code=201)
async def create_workout(
    body: WorkoutCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.create_workout(db, current_user["_id"], body)


@router.get("/{workout_id}", response_model=WorkoutDetail)
async def get_workout(
    workout_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.get_workout(db, current_user["_id"], workout_id)


@router.put("/{workout_id}", response_model=WorkoutDetail)
async def update_workout(
    workout_id: str,
    body: WorkoutUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.update_workout(db, current_user["_id"], workout_id, body)


@router.patch("/{workout_id}", response_model=WorkoutDetail)
async def patch_workout(
    workout_id: str,
    body: WorkoutUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Partially update a workout — notably reschedule it (``{"date": "YYYY-MM-DD"}``).
    Its logged sets move with it. Used by the coach's ``move_workout`` action."""
    return await service.update_workout(db, current_user["_id"], workout_id, body)


@router.delete("/{workout_id}", status_code=204)
async def delete_workout(
    workout_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    await service.delete_workout(db, current_user["_id"], workout_id)


@router.post("/{workout_id}/muscle-groups", response_model=WorkoutDetail)
async def add_muscle_group(
    workout_id: str,
    body: MuscleGroupAdd,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.add_muscle_group(db, current_user["_id"], workout_id, body.muscle)


@router.delete("/{workout_id}/muscle-groups/{muscle}", response_model=WorkoutDetail)
async def remove_muscle_group(
    workout_id: str,
    muscle: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.remove_muscle_group(db, current_user["_id"], workout_id, muscle)


@router.post("/{workout_id}/exercises", response_model=WorkoutDetail)
async def add_workout_exercise(
    workout_id: str,
    body: WorkoutExerciseAdd,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Add an exercise to this workout (found-or-created in the shared catalog)."""
    return await service.add_workout_exercise(db, current_user["_id"], workout_id, body)


@router.delete("/{workout_id}/exercises/{exercise_id}", response_model=WorkoutDetail)
async def remove_workout_exercise(
    workout_id: str,
    exercise_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Remove an exercise from this workout only (keeps its history elsewhere)."""
    return await service.remove_workout_exercise(
        db, current_user["_id"], workout_id, exercise_id
    )
