"""IronLog API application package.

`create_app()` is the composition root: it builds the FastAPI instance,
wires middleware, exception handlers, and the per-feature routers.
"""
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import DEFAULT_SECRET_KEY, settings
from app.core.database import close_db, connect_db
from app.helpers.exceptions import register_exception_handlers

logger = logging.getLogger(__name__)


class _JsonLogFormatter(logging.Formatter):
    """Minimal structured (one JSON object per line) log formatter, so the many
    logger.* calls across the app surface consistently and stay greppable in
    Azure Log Stream / log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_logging() -> None:
    """Route the root logger through a single structured handler at LOG_LEVEL."""
    level = logging.getLevelName(settings.LOG_LEVEL.upper())
    if not isinstance(level, int):
        level = logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def _enforce_secure_config() -> None:
    """Fail fast on fatal insecure config; warn on risky config.

    - SECRET_KEY: signing JWTs with the shipped placeholder is a full auth
      bypass, so refuse to boot on it outside an explicit dev environment.
    - CORS: a wildcard origin allowlist in production is over-permissive — warn
      (don't hard-fail) so it surfaces in the logs without breaking a running
      deployment.
    """
    if settings.SECRET_KEY == DEFAULT_SECRET_KEY:
        msg = (
            "SECRET_KEY is the insecure default placeholder — signing JWTs with "
            "it is a full auth bypass. Set a strong random SECRET_KEY (see README)."
        )
        if settings.is_dev_env:
            logger.warning("%s Allowed because ENV=%r.", msg, settings.ENV)
        else:
            raise RuntimeError(
                f"{msg} Or set ENV=dev to allow the placeholder for local development."
            )

    if not settings.is_dev_env and "*" in settings.CORS_ORIGINS:
        logger.warning(
            "CORS_ORIGINS allows all origins ('*') in a non-dev environment. Set an "
            'explicit allowlist, e.g. CORS_ORIGINS=["https://app.example.com"].'
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the Mongo connection on startup, close it on shutdown."""
    await connect_db()
    # Ensure the chat-memory indexes exist (idempotent). Best-effort: indexes are
    # a performance optimisation, not a correctness requirement, so a transient
    # DB hiccup here must not stop the API from starting.
    from app.auth.models import ensure_indexes as ensure_auth_indexes
    from app.coach.models import ensure_indexes as ensure_coach_indexes
    from app.conversations.models import ensure_indexes
    from app.core.database import get_db
    from app.exercises.models import ensure_indexes as ensure_exercise_indexes
    from app.goals.models import ensure_indexes as ensure_goal_indexes
    from app.sessions.models import ensure_indexes as ensure_session_indexes
    from app.workouts.models import ensure_indexes as ensure_workout_indexes

    db = get_db()
    for label, ensure in (
        ("auth", ensure_auth_indexes),
        ("chat-memory", ensure_indexes),
        ("coach", ensure_coach_indexes),
        ("goals", ensure_goal_indexes),
        ("exercises", ensure_exercise_indexes),
        ("sessions", ensure_session_indexes),
        ("workouts", ensure_workout_indexes),
    ):
        try:
            await ensure(db)
        except Exception:
            logger.exception("Could not ensure %s indexes on startup", label)
    try:
        yield
    finally:
        await close_db()


def create_app() -> FastAPI:
    # Structured logging first, so the config check below logs consistently.
    _configure_logging()
    # Refuse to boot with an insecure production configuration (see above).
    _enforce_secure_config()

    app = FastAPI(
        title="IronLog API",
        description="Backend for IronLog fitness tracker",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── Rate limiting (slowapi) — blunts brute-force on the auth endpoints ──
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from app.core.rate_limit import limiter

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── CORS (lets the mobile app call this API) ──
    # This is a Bearer-token API (no cookies), so credentials mode stays off —
    # that's also what makes an explicit origin allowlist meaningful, since
    # allow_origins=["*"] with allow_credentials=True is an invalid combination.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Map domain errors (NotFoundError, ...) to JSON responses ──
    register_exception_handlers(app)

    # ── Routers (imported here to keep the import graph flat) ──
    from app.auth.router import router as auth_router
    from app.chat.router import router as chat_router
    from app.coach.router import router as coach_router
    from app.conversations.router import router as conversations_router
    from app.exercises.router import router as exercises_router
    from app.goals.router import router as goals_router
    from app.library.router import router as library_router
    from app.muscles.router import router as muscles_router
    from app.progress.router import router as progress_router
    from app.sessions.router import router as sessions_router
    from app.workouts.router import router as workouts_router

    app.include_router(auth_router,          prefix="/auth",          tags=["Auth"])
    app.include_router(muscles_router,       prefix="/muscles",       tags=["Muscles"])
    app.include_router(exercises_router,     prefix="/exercises",     tags=["Exercises"])
    app.include_router(library_router,       prefix="/exercise-library", tags=["Exercise Library"])
    app.include_router(workouts_router,      prefix="/workouts",      tags=["Workouts"])
    app.include_router(sessions_router,      prefix="/sessions",      tags=["Sessions"])
    app.include_router(progress_router,      prefix="/progress",      tags=["Progress"])
    app.include_router(chat_router,          prefix="/chat",          tags=["AI Chat"])
    app.include_router(coach_router,         prefix="/coach",         tags=["AI Coach"])
    app.include_router(goals_router,         prefix="/goals",         tags=["Goals"])
    app.include_router(conversations_router, prefix="/conversations", tags=["Conversations"])

    @app.get("/", tags=["Health"])
    def root():
        return {"status": "IronLog API is running 💪"}

    @app.get("/health", tags=["Health"])
    async def health():
        """Readiness probe: 200 when MongoDB answers a ping, 503 otherwise — so
        Azure/monitoring can tell 'process up' from 'DB reachable'."""
        from app.core.database import get_db

        try:
            await get_db().command("ping")
        except Exception:
            logger.warning("Health check: database ping failed")
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "database": "unreachable"},
            )
        return {"status": "ok", "database": "ok"}

    return app
