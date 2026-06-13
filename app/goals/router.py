"""Goal endpoints: CRUD + trajectory under /goals."""
from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.goals import service
from app.goals.schemas import GoalCreate, GoalResponse, GoalTrajectory, GoalUpdate

router = APIRouter()


@router.get("", response_model=list[GoalResponse])
async def list_goals(
    status: str | None = Query(None, description="Filter by status"),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.list_goals(db, current_user["_id"], status)


@router.post("", response_model=GoalResponse, status_code=201)
async def create_goal(
    body: GoalCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.create_goal(db, current_user["_id"], body)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.get_goal(db, current_user["_id"], goal_id)


# Declared distinctly from "/{goal_id}" — the extra segment makes the route unambiguous.
@router.get("/{goal_id}/trajectory", response_model=GoalTrajectory)
async def get_goal_trajectory(
    goal_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.get_trajectory(db, current_user["_id"], goal_id)


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: str,
    body: GoalUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.update_goal(db, current_user["_id"], goal_id, body)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    await service.delete_goal(db, current_user["_id"], goal_id)
