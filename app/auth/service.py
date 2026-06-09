"""Business logic for registration, login, and profile management."""
from app.auth.models import COLLECTION, UserDocument
from app.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.helpers.exceptions import BadRequestError, UnauthorizedError


def serialize_user(user: dict) -> UserResponse:
    return UserResponse(
        id=str(user["_id"]),
        name=user["name"],
        email=user["email"],
        username=user.get("username"),
        gender=user.get("gender"),
        height_cm=user.get("height_cm"),
        weight_kg=user.get("weight_kg"),
        created_at=user["created_at"],
    )


async def register(db, body: RegisterRequest) -> TokenResponse:
    if await db[COLLECTION].find_one({"email": body.email}):
        raise BadRequestError("Email already registered")

    doc = UserDocument(
        name=body.name,
        email=body.email,
        password=hash_password(body.password),
    ).model_dump()
    result = await db[COLLECTION].insert_one(doc)
    user_id = str(result.inserted_id)

    token = create_access_token({"sub": user_id})
    return TokenResponse(access_token=token, user_id=user_id, name=body.name)


async def login(db, body: LoginRequest) -> TokenResponse:
    user = await db[COLLECTION].find_one({"email": body.email})
    if not user or not verify_password(body.password, user["password"]):
        raise UnauthorizedError("Invalid email or password")

    user_id = str(user["_id"])
    token = create_access_token({"sub": user_id})
    return TokenResponse(access_token=token, user_id=user_id, name=user["name"])


async def update_profile(db, user: dict, body: UpdateProfileRequest) -> UserResponse:
    update: dict = {}
    if body.name is not None:
        update["name"] = body.name
    if body.password is not None:
        update["password"] = hash_password(body.password)
    if body.username is not None:
        update["username"] = body.username
    if body.gender is not None:
        update["gender"] = body.gender
    if body.height_cm is not None:
        update["height_cm"] = body.height_cm
    if body.weight_kg is not None:
        update["weight_kg"] = body.weight_kg

    if update:
        await db[COLLECTION].update_one({"_id": user["_id"]}, {"$set": update})
        user.update(update)

    return serialize_user(user)
