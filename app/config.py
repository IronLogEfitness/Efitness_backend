from pydantic_settings import BaseSettings, SettingsConfigDict

# The shipped placeholder JWT secret. Signing real tokens with a value an
# attacker can read from source is a full auth bypass, so create_app refuses to
# boot on it outside an explicit dev environment (see app.__init__).
DEFAULT_SECRET_KEY = "change-this-to-a-random-secret-in-production"

# ENV values treated as "local development" by the startup safety checks.
DEV_ENVIRONMENTS = frozenset({"dev", "development", "local", "test"})


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Deployment ──
    # Anything not in DEV_ENVIRONMENTS is treated as production for the startup
    # safety checks (secure by default: an unset ENV means "production").
    ENV: str = "production"
    # Root log level (DEBUG/INFO/WARNING/ERROR). Logs are emitted as structured
    # JSON lines so they stay greppable in Azure Log Stream.
    LOG_LEVEL: str = "INFO"

    # ── Rate limiting ── (brute-force protection on the auth endpoints)
    AUTH_RATE_LIMIT: str = "10/minute"

    # ── MongoDB ──
    MONGO_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "ironlog"

    # ── JWT ──
    SECRET_KEY: str = DEFAULT_SECRET_KEY
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

    @property
    def is_dev_env(self) -> bool:
        """True when ENV marks this as a local/dev/test environment."""
        return self.ENV.strip().lower() in DEV_ENVIRONMENTS


settings = Settings()
