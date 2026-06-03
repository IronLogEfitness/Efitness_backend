"""Request / response models for the auth endpoints."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2)
    password: str | None = Field(default=None, min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime
