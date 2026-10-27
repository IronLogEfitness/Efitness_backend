"""API-level tests: drive the real ASGI app in-process (httpx ASGITransport)
against an in-memory Mongo, covering the critical flows end to end — auth, the
PR-detection log path, and confirm idempotency (double-confirm doesn't
double-write). Complements the pure-logic and aggregation-parity suites."""
from uuid import uuid4

import pytest_asyncio
from bson import ObjectId
from httpx import ASGITransport, AsyncClient

from app.config import settings


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    # A real (non-placeholder) secret so create_app's boot guard passes and the
    # JWTs sign/verify consistently within the test.
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret-key")

    from app import create_app
    from app.core.database import get_db

    app = create_app()
    # Route every get_db dependency (endpoints + get_current_user) at the mock DB.
    app.dependency_overrides[get_db] = lambda: db
    app.state.limiter.enabled = False  # don't rate-limit the test's many calls

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _register(client, email="lifter@example.com"):
    resp = await client.post(
        "/auth/register",
        json={"name": "Test Lifter", "email": email, "password": "secret123"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_register_login_and_me(client):
    await _register(client)

    # Duplicate registration is rejected with the friendly message (status + shape).
    dup = await client.post(
        "/auth/register",
        json={"name": "Someone", "email": "lifter@example.com", "password": "secret123"},
    )
    assert dup.status_code == 400
    assert dup.json()["detail"] == "Email already registered"

    # Login succeeds; a wrong password is 401.
    ok = await client.post(
        "/auth/login", json={"email": "lifter@example.com", "password": "secret123"}
    )
    assert ok.status_code == 200
    bad = await client.post(
        "/auth/login", json={"email": "lifter@example.com", "password": "wrong"}
    )
    assert bad.status_code == 401

    # The token authenticates /auth/me; no token is rejected.
    me = await client.get("/auth/me", headers=_auth(ok.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "lifter@example.com"
    assert (await client.get("/auth/me")).status_code in (401, 403)


async def test_create_exercise_log_session_pr_detection(client):
    h = _auth(await _register(client))

    ex = await client.post(
        "/exercises", json={"muscle": "chest", "name": "Bench Press"}, headers=h
    )
    assert ex.status_code == 201, ex.text
    exercise_id = ex.json()["id"]

    # First log at 60kg — a first-ever lift above 0kg is a PR.
    s1 = await client.post(
        "/sessions",
        json={"exercise_id": exercise_id, "sets": [{"set_number": 1, "weight_kg": 60, "reps": 5}]},
        headers=h,
    )
    assert s1.status_code == 201, s1.text
    assert s1.json()["pr"] == {"is_pr": True, "value": 60, "prev_best": None}

    # Heavier log at 70kg beats the prior best → PR with prev_best 60.
    s2 = await client.post(
        "/sessions",
        json={"exercise_id": exercise_id, "sets": [{"set_number": 1, "weight_kg": 70, "reps": 3}]},
        headers=h,
    )
    assert s2.json()["pr"] == {"is_pr": True, "value": 70, "prev_best": 60}

    # A lighter log at 50kg is not a PR.
    s3 = await client.post(
        "/sessions",
        json={"exercise_id": exercise_id, "sets": [{"set_number": 1, "weight_kg": 50, "reps": 8}]},
        headers=h,
    )
    assert s3.json()["pr"] is None

    # The exercise's personal best reflects the heaviest lift, and the overview
    # counts the PR this month.
    detail = await client.get(f"/exercises/{exercise_id}", headers=h)
    assert detail.json()["personal_best"] == 70
    overview = await client.get("/progress/overview", headers=h)
    assert overview.json()["prs_this_month"] >= 1


async def test_confirm_is_idempotent(client, db):
    """Re-confirming an accepted coach action is a no-op that returns the stored
    created_id instead of writing a second row."""
    from app.conversations import service as conversations
    from app.coach.models import COACH_ACTIONS_COLLECTION, CoachActionDocument
    from app.exercises.models import COLLECTION as EXERCISES

    h = _auth(await _register(client))
    user_id = ObjectId((await client.get("/auth/me", headers=h)).json()["id"])

    # Seed a conversation + one pending create_exercise action (the LLM turn would
    # normally emit this) so /chat/confirm can run without Gemini.
    conv = await conversations.create_conversation(db, user_id, title="t")
    action_id = uuid4().hex
    await db[COACH_ACTIONS_COLLECTION].insert_one(
        CoachActionDocument(
            conversation_id=conv["_id"],
            user_id=user_id,
            action_id=action_id,
            type="create_exercise",
            args={"muscle": "back", "name": "Barbell Row", "emoji": "🏋️"},
            summary="Create exercise Barbell Row",
        ).model_dump()
    )

    body = {
        "conversation_id": str(conv["_id"]),
        "accepted_ids": [action_id],
        "rejected_ids": [],
    }

    first = await client.post("/chat/confirm", json=body, headers=h)
    assert first.status_code == 200, first.text
    r1 = first.json()["results"][0]
    assert r1["status"] == "executed"
    created_id = r1["created_id"]
    assert await db[EXERCISES].count_documents({"user_id": user_id}) == 1

    second = await client.post("/chat/confirm", json=body, headers=h)
    r2 = second.json()["results"][0]
    assert r2["status"] == "already_executed"
    assert r2["created_id"] == created_id
    # Crucially: no second exercise row was written.
    assert await db[EXERCISES].count_documents({"user_id": user_id}) == 1
