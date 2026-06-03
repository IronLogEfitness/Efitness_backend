from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    DB_NAME:   str = "ironlog"

    # JWT
    SECRET_KEY:  str = "change-this-to-a-random-secret-in-production"
    ALGORITHM:   str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    class Config:
        env_file = ".env"

settings = Settings()