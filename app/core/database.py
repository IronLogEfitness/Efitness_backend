"""MongoDB connection lifecycle.

A single AsyncIOMotorClient is created on app startup and shared across
requests. `get_db` is used as a FastAPI dependency by the routers.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    global _client, _db
    # tz_aware=True so datetimes read back from Mongo are timezone-aware (UTC),
    # matching the timezone-aware values we write with helpers.dates.now_utc().
    _client = AsyncIOMotorClient(settings.MONGO_URI, tz_aware=True)
    _db = _client[settings.DB_NAME]


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError(
            "Database is not connected. Start the app to initialize the DB connection."
        )
    return _db
