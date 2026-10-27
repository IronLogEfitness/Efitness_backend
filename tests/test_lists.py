"""Parity / shape tests for the N+1 removals in the exercise and muscle lists.

Both endpoints previously ran per-item queries (personal-best + last-session per
exercise; count + last-trained lookup per muscle). The rewrites compute the same
values in a single aggregation. These pin the response shape and the derived
stats, including the empty paths (no sessions / no exercises).
"""
from datetime import datetime, time, timedelta, timezone

from bson import ObjectId

from app.exercises import service as ex_service
from app.exercises.models import COLLECTION as EX
from app.muscles import service as mu_service
from app.muscles.constants import MUSCLE_GROUPS
from app.sessions.models import COLLECTION as SE

EXERCISE_KEYS = {
    "id", "muscle", "name", "emoji", "image_url",
    "personal_best", "last_session_summary", "set_count",
}


def _at(d, hour=8):
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


def _sets(*weights):
    return [{"set_number": i + 1, "weight_kg": w, "reps": 5} for i, w in enumerate(weights)]


async def test_list_exercises_shape_and_stats(db, monkeypatch):
    # Freeze now so the "x days ago" label is deterministic.
    fixed_now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(ex_service, "now_utc", lambda: fixed_now)
    today = fixed_now.date()

    uid = ObjectId()
    bench, fly = ObjectId(), ObjectId()
    await db[EX].insert_many([
        {"_id": bench, "user_id": uid, "muscle": "chest", "name": "Bench", "emoji": "🏋️",
         "image_url": None, "created_at": _at(today - timedelta(days=2))},
        {"_id": fly, "user_id": uid, "muscle": "chest", "name": "Fly", "emoji": "🦋",
         "image_url": "http://img/fly.png", "created_at": _at(today - timedelta(days=1))},
    ])
    await db[SE].insert_many([
        {"user_id": uid, "exercise_id": bench, "date": _at(today - timedelta(days=3)),
         "sets": _sets(60, 80)},                       # all-time heaviest set = 80
        {"user_id": uid, "exercise_id": bench, "date": _at(today),
         "sets": _sets(70)},                           # most recent session: 1 set
    ])

    out = await ex_service.list_exercises(db, uid)

    # Ordered by created_at ascending.
    assert [e["name"] for e in out] == ["Bench", "Fly"]
    assert all(set(e.keys()) == EXERCISE_KEYS for e in out)

    b = out[0]
    assert b["id"] == str(bench)
    assert b["muscle"] == "chest"
    assert b["emoji"] == "🏋️"
    assert b["image_url"] is None
    assert b["personal_best"] == 80           # max across every set of every session
    assert b["set_count"] == 1                # from the most-recent session (today)
    assert b["last_session_summary"] == "1 set · today"

    f = out[1]                                 # no sessions logged
    assert f["image_url"] == "http://img/fly.png"
    assert f["personal_best"] is None
    assert f["set_count"] is None
    assert f["last_session_summary"] is None


async def test_list_exercises_muscle_filter(db):
    uid = ObjectId()
    chest_ex, back_ex = ObjectId(), ObjectId()
    await db[EX].insert_many([
        {"_id": chest_ex, "user_id": uid, "muscle": "chest", "name": "Bench", "emoji": "🏋️",
         "image_url": None, "created_at": _at(datetime(2026, 1, 1).date())},
        {"_id": back_ex, "user_id": uid, "muscle": "back", "name": "Row", "emoji": "🏋️",
         "image_url": None, "created_at": _at(datetime(2026, 1, 2).date())},
    ])

    out = await ex_service.list_exercises(db, uid, muscle="Chest")  # case-insensitive
    assert [e["name"] for e in out] == ["Bench"]


async def test_list_muscles_shape_and_stats(db):
    uid = ObjectId()
    bench, fly, pull = ObjectId(), ObjectId(), ObjectId()
    d1 = datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
    d2 = datetime(2026, 10, 25, 8, tzinfo=timezone.utc)
    await db[EX].insert_many([
        {"_id": bench, "user_id": uid, "muscle": "chest", "name": "Bench", "emoji": "🏋️", "image_url": None, "created_at": d1},
        {"_id": fly, "user_id": uid, "muscle": "chest", "name": "Fly", "emoji": "🦋", "image_url": None, "created_at": d1},
        {"_id": pull, "user_id": uid, "muscle": "back", "name": "Pull", "emoji": "🏋️", "image_url": None, "created_at": d1},
    ])
    await db[SE].insert_many([
        {"user_id": uid, "exercise_id": bench, "date": d1, "sets": _sets(60)},
        {"user_id": uid, "exercise_id": bench, "date": d2, "sets": _sets(65)},
        # fly and pull have no sessions.
    ])

    out = await mu_service.list_muscles(db, uid)

    # All 8 groups, in MUSCLE_GROUPS order.
    assert [m.muscle for m in out] == MUSCLE_GROUPS
    by = {m.muscle: m for m in out}
    assert by["chest"].exercise_count == 2
    assert by["chest"].last_trained == d2       # most recent across the muscle
    assert by["back"].exercise_count == 1
    assert by["back"].last_trained is None       # its only exercise has no sessions
    assert by["legs"].exercise_count == 0        # no exercises
    assert by["legs"].last_trained is None
