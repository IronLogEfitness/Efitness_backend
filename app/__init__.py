"""IronLog API application package.

`create_app()` is the composition root: it builds the FastAPI instance,
wires middleware, exception handlers, and the per-feature routers.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.database import close_db, connect_db
from app.helpers.exceptions import register_exception_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the Mongo connection on startup, close it on shutdown."""
    await connect_db()
    # Ensure the chat-memory indexes exist (idempotent). Best-effort: indexes are
    # a performance optimisation, not a correctness requirement, so a transient
    # DB hiccup here must not stop the API from starting.
    from app.conversations.models import ensure_indexes
    from app.core.database import get_db

    try:
        await ensure_indexes(get_db())
    except Exception:
        logger.exception("Could not ensure chat-memory indexes on startup")
    try:
        yield
    finally:
        await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="IronLog API",
        description="Backend for IronLog fitness tracker",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── CORS (lets the mobile app call this API) ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Map domain errors (NotFoundError, ...) to JSON responses ──
    register_exception_handlers(app)

    # ── Routers (imported here to keep the import graph flat) ──
    from app.auth.router import router as auth_router
    from app.chat.router import router as chat_router
    from app.conversations.router import router as conversations_router
    from app.exercises.router import router as exercises_router
    from app.muscles.router import router as muscles_router
    from app.progress.router import router as progress_router
    from app.sessions.router import router as sessions_router

    app.include_router(auth_router,          prefix="/auth",          tags=["Auth"])
    app.include_router(muscles_router,       prefix="/muscles",       tags=["Muscles"])
    app.include_router(exercises_router,     prefix="/exercises",     tags=["Exercises"])
    app.include_router(sessions_router,      prefix="/sessions",      tags=["Sessions"])
    app.include_router(progress_router,      prefix="/progress",      tags=["Progress"])
    app.include_router(chat_router,          prefix="/chat",          tags=["AI Chat"])
    app.include_router(conversations_router, prefix="/conversations", tags=["Conversations"])

    @app.get("/", tags=["Health"])
    def root():
        return {"status": "IronLog API is running 💪"}

    return app
