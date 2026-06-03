from motor.motor_asyncio import AsyncIOMotorClient
from config import settings


client: AsyncIOMotorClient | None = None
_db = None


async def connect_db() -> None:
    global client, _db
    client = AsyncIOMotorClient(settings.MONGO_URI)
    _db = client[settings.DB_NAME]


async def close_db() -> None:
    global client
    if client is not None:
        client.close()
        client = None


def get_db():
    if _db is None:
        raise RuntimeError("Database is not connected. Start the app to initialize DB connection.")
    return _db
