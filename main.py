from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import auth
import exercices
import exercises
import sessions
import progress
import chat
from database import connect_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    try:
        yield
    finally:
        await close_db()

app = FastAPI(
    title="IronLog API",
    description="Backend for IronLog fitness tracker",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS (allows your mobile app to call this API) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict this to your app's domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──
app.include_router(auth.router,      prefix="/auth",      tags=["Auth"])
app.include_router(exercices.router, prefix="/muscles",   tags=["Muscles"])
app.include_router(exercises.router, prefix="/exercises", tags=["Exercises"])
app.include_router(sessions.router,  prefix="/sessions",  tags=["Sessions"])
app.include_router(progress.router,  prefix="/progress",  tags=["Progress"])
app.include_router(chat.router,      prefix="/chat",      tags=["AI Chat"])

@app.get("/")
def root():
    return {"status": "IronLog API is running 💪"}