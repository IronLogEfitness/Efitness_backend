"""Progress endpoints: /progress/overview and /progress/exercise/{id}."""
from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.progress import service
from app.progress.schemas import ExerciseProgressResponse, OverviewResponse

router = APIRouter()


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(current_user=Depends(get_current_user), db=Depends(get_db)):
    return await service.get_overview(db, current_user["_id"])


@router.get("/exercise/{exercise_id}", response_model=ExerciseProgressResponse)
async def get_exercise_progress(
    exercise_id: str,
    days: int = Query(default=90, description="How many days back to look"),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.get_exercise_progress(db, current_user["_id"], exercise_id, days)
