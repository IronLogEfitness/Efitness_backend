"""Request / response models for the auth endpoints."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Gender = Literal["male", "female", "other"]


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
    username: str | None = Field(default=None, min_length=2, max_length=30)
    gender: Gender | None = None
    height_cm: float | None = Field(default=None, gt=0, lt=300)
    weight_kg: float | None = Field(default=None, gt=0, lt=600)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    username: str | None = None
    gender: Gender | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    created_at: datetime
