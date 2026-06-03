from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── MongoDB ──
    MONGO_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "ironlog"

    # ── JWT ──
    SECRET_KEY: str = "change-this-to-a-random-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # ── Google Gemini (AI chat) ──
    GEMINI_API_KEY: str = ""

    # ── CORS ── (JSON array in the env var, e.g. ["https://app.example.com"])
    CORS_ORIGINS: list[str] = ["*"]


settings = Settings()
