"""Auth endpoints: /auth/register, /auth/login, /auth/me."""
from fastapi import APIRouter, Depends, Request

from app.auth import service
from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.core.database import get_db
from app.core.rate_limit import auth_rate_limit, limiter

router = APIRouter()


# Rate-limited per client IP to blunt credential brute-force / signup abuse. The
# `request` param is required by slowapi; the response shape is unchanged.
@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit(auth_rate_limit)
async def register(request: Request, body: RegisterRequest, db=Depends(get_db)):
    return await service.register(db, body)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(auth_rate_limit)
async def login(request: Request, body: LoginRequest, db=Depends(get_db)):
    return await service.login(db, body)


@router.get("/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    return service.serialize_user(current_user)


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UpdateProfileRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.update_profile(db, current_user, body)
