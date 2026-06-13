"""The read-only /coach namespace: briefing, recap, progression, balance.

All four are deterministic (and recap/briefing are cached), so they're cheap to
hit on app-open. They never write — acting on the user's app goes through the
propose/confirm flow in /chat and /chat/confirm.
"""
from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.coach import briefing, progression, recap
from app.coach.balance import audit_balance
from app.coach.schemas import (
    BalanceResponse,
    BriefingResponse,
    ProgressionResponse,
    RecapResponse,
)
from app.core.database import get_db
from app.progress import service as progress_service

router = APIRouter()


@router.get("/briefing", response_model=BriefingResponse)
async def get_briefing(current_user=Depends(get_current_user), db=Depends(get_db)):
    return await briefing.get_briefing(db, current_user["_id"])


@router.get("/recap", response_model=RecapResponse)
async def get_recap(
    week: str | None = Query(None, description="ISO week, e.g. 2026-W24 (default: this week)"),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await recap.get_recap(db, current_user["_id"], week)


@router.get("/progression", response_model=ProgressionResponse)
async def get_progression(
    workout_ref: str = Query(..., description="The workout: 'today', YYYY-MM-DD, or its title"),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await progression.build_progression(db, current_user["_id"], workout_ref)


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(current_user=Depends(get_current_user), db=Depends(get_db)):
    overview = await progress_service.get_overview(db, current_user["_id"])
    audit = audit_balance([m.model_dump() for m in overview.muscle_breakdown])
    return BalanceResponse(**audit)
