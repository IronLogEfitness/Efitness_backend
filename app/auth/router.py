"""Auth endpoints: /auth/register, /auth/login, /auth/me."""
from fastapi import APIRouter, Depends

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

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db=Depends(get_db)):
    return await service.register(db, body)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db=Depends(get_db)):
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
