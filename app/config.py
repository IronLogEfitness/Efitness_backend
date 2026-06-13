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

    # ── AI chat memory (sliding window + summarisation) ──
    # Raw messages kept in the active context after summarising older ones.
    CHAT_HISTORY_LIMIT: int = 10
    # Once the active window (summary + unsummarised turns) exceeds this many
    # tokens, older turns are folded into the conversation summary.
    CHAT_SUMMARY_TOKEN_THRESHOLD: int = 4000

    # ── Agentic coach (function calling + human-in-the-loop) ──
    # Hard cap on the chat tool loop: how many read→call→read rounds Gemini may
    # take before we stop. Protects the free-tier request quota.
    COACH_MAX_TOOL_ITERATIONS: int = 5
    # Optional Gemini phrasing (off = templated, zero quota). Deterministic
    # aggregation always runs in code; these only control the *wording* call.
    COACH_CONFIRM_USE_LLM: bool = False   # confirmation sentence after /chat/confirm
    COACH_BRIEFING_USE_LLM: bool = False  # pre-workout one-liner
    COACH_RECAP_USE_LLM: bool = True      # weekly "wrapped" recap (1 call/week, cached)

    # ── CORS ── (JSON array in the env var, e.g. ["https://app.example.com"])
    CORS_ORIGINS: list[str] = ["*"]


settings = Settings()
