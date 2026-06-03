from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from schema import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from security import hash_password, verify_password, create_access_token, get_current_user
from database import get_db

router = APIRouter()

# ─────────────────────────────────────────────────────────
#  POST /auth/register
#  Create a new account.
# ─────────────────────────────────────────────────────────
@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, db=Depends(get_db)):
    # Check email not already taken
    if await db["users"].find_one({"email": body.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    user = {
        "name":       body.name,
        "email":      body.email,
        "password":   hash_password(body.password),
        "created_at": datetime.utcnow(),
    }
    result = await db["users"].insert_one(user)
    user_id = str(result.inserted_id)

    token = create_access_token({"sub": user_id})
    return TokenResponse(access_token=token, user_id=user_id, name=body.name)


# ─────────────────────────────────────────────────────────
#  POST /auth/login
#  Returns a JWT token.
# ─────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db=Depends(get_db)):
    user = await db["users"].find_one({"email": body.email})
    if not user or not verify_password(body.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id = str(user["_id"])
    token = create_access_token({"sub": user_id})
    return TokenResponse(access_token=token, user_id=user_id, name=user["name"])


# ─────────────────────────────────────────────────────────
#  GET /auth/me
#  Returns the logged-in user's profile.
# ─────────────────────────────────────────────────────────
@router.get("/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    return UserResponse(
        id=str(current_user["_id"]),
        name=current_user["name"],
        email=current_user["email"],
        created_at=current_user["created_at"],
    )


# ─────────────────────────────────────────────────────────
#  PUT /auth/me
#  Update name or password.
# ─────────────────────────────────────────────────────────
@router.put("/me", response_model=UserResponse)
async def update_me(
    body: dict,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    update = {}
    if "name" in body:
        update["name"] = body["name"]
    if "password" in body:
        update["password"] = hash_password(body["password"])

    if update:
        await db["users"].update_one({"_id": current_user["_id"]}, {"$set": update})
        current_user.update(update)

    return UserResponse(
        id=str(current_user["_id"]),
        name=current_user["name"],
        email=current_user["email"],
        created_at=current_user["created_at"],
    )