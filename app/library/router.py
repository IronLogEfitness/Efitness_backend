"""Exercise-library endpoint: GET /exercise-library.

Read-only catalog search used by the client's add-exercise picker. Filtering is
by query param (?muscle=&q=&limit=), keeping single-resource routes on path
params as elsewhere.
"""
from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user
from app.library import service
from app.library.schemas import LibraryExercise

router = APIRouter()


@router.get("", response_model=list[LibraryExercise])
async def search_library(
    muscle: str | None = Query(None, description="Muscle group, e.g. chest"),
    q: str = Query("", description="Name search; empty returns the muscle's exercises"),
    limit: int = Query(30, ge=1, le=100, description="Max results"),
    current_user=Depends(get_current_user),
):
    return service.search(q, muscle, limit)
