"""Authentication dependency shared by every protected route.

`get_current_user` reads the Bearer token, validates it, and returns the user
document. Other features import it from here.
"""
from bson import ObjectId
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import COLLECTION
from app.core.database import get_db
from app.core.security import decode_access_token
from app.helpers.exceptions import UnauthorizedError

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db=Depends(get_db),
) -> dict:
    user_id = decode_access_token(credentials.credentials)
    if not user_id or not ObjectId.is_valid(user_id):
        raise UnauthorizedError("Invalid or expired token")

    user = await db[COLLECTION].find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise UnauthorizedError("Invalid or expired token")
    return user
