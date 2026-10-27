"""Password hashing and JWT helpers.

Pure functions with no FastAPI dependencies, so they are easy to unit-test.
The request-time "who is the current user" logic lives in
`app.auth.dependencies` instead.
"""
from datetime import timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.helpers.dates import now_utc

# pbkdf2_sha256 for broad compatibility on Windows / Python 3.12.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


# ── Passwords ──
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ──
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = now_utc() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the user id stored in the token's `sub` claim, or None if invalid."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        return None
    return payload.get("sub")
