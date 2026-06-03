"""Muscle endpoints: GET /muscles."""
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.muscles import service
from app.muscles.schemas import MuscleSummary

router = APIRouter()


@router.get("", response_model=list[MuscleSummary])
async def get_muscles(current_user=Depends(get_current_user), db=Depends(get_db)):
    return await service.list_muscles(db, current_user["_id"])
