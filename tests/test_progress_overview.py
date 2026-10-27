"""Parity tests for the progress-overview aggregation rewrite.

The previous implementation issued an unbounded number of sequential queries: a
per-day streak loop (up to 365), two aggregations per exercise for the PR count,
and a distinct+count+setcount+find per muscle group. The rewrite collapses these
into a small, fixed set of aggregations. These tests assert it returns identical
OverviewResponse objects.

  * ``test_overview_matches_old_reference`` runs an inline copy of the OLD logic
    and asserts ``new == old`` on a fully-populated dataset. The dataset is
    deliberately arranged so every old ``$group {_id: None}`` sees non-empty
    input — mongomock materialises an empty such group differently from real
    MongoDB, so the reference only runs cleanly on populated data.
  * ``test_overview_edge_cases`` pins exact values for the paths the reference
    can't cover under mongomock: a brand-new exercise (PR up from zero), an
    exercise with no sessions, and untrained muscle groups.
"""
from datetime import datetime, time, timedelta, timezone

from bson import ObjectId

from app.exercises.models import COLLECTION as EX
from app.helpers.dates import now_utc
from app.muscles.constants import MUSCLE_GROUPS
from app.progress import service as progress_service
from app.progress.schemas import MuscleStats, OverviewResponse
from app.sessions.models import COLLECTION as SE


def _at(d, hour=8):
    """A tz-aware UTC datetime at the given hour on date ``d``."""
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


def _sets(*weights):
    return [{"set_number": i + 1, "weight_kg": w, "reps": 5} for i, w in enumerate(weights)]


async def _insert(db, user_id, exercises, sessions):
    await db[EX].insert_many(
        [{"_id": ex_id, "user_id": user_id, **fields} for ex_id, fields in exercises]
    )
    if sessions:
        await db[SE].insert_many(sessions)


# ─────────────────────────────────────────────────────────────────────────────
# Inline reference: the overview exactly as it was before the rewrite.
# ─────────────────────────────────────────────────────────────────────────────
async def _old_overview(db, user_id) -> OverviewResponse:
    now = now_utc()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def count_sets(match):
        agg = await db[SE].aggregate(
            [
                {"$match": match},
                {"$project": {"count": {"$size": "$sets"}}},
                {"$group": {"_id": None, "total": {"$sum": "$count"}}},
            ]
        ).to_list(1)
        return agg[0]["total"] if agg else 0

    total_sessions = await db[SE].count_documents({"user_id": user_id})
    total_sets = await count_sets({"user_id": user_id})
    total_exercises = await db[EX].count_documents({"user_id": user_id})

    exercise_ids = await db[EX].distinct("_id", {"user_id": user_id})
    prs = 0
    for ex_id in exercise_ids:
        before = await db[SE].aggregate(
            [
                {"$match": {"user_id": user_id, "exercise_id": ex_id, "date": {"$lt": month_start}}},
                {"$unwind": "$sets"},
                {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
            ]
        ).to_list(1)
        prev_pr = before[0]["max"] if before else 0
        this_month = await db[SE].aggregate(
            [
                {"$match": {"user_id": user_id, "exercise_id": ex_id, "date": {"$gte": month_start}}},
                {"$unwind": "$sets"},
                {"$group": {"_id": None, "max": {"$max": "$sets.weight_kg"}}},
            ]
        ).to_list(1)
        this_max = this_month[0]["max"] if this_month else 0
        if this_max > prev_pr:
            prs += 1

    today = now_utc().date()
    streak = 0
    day = today
    for _ in range(365):
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day, time.max, tzinfo=timezone.utc)
        count = await db[SE].count_documents(
            {"user_id": user_id, "date": {"$gte": start, "$lte": end}}
        )
        if count > 0:
            streak += 1
            day -= timedelta(days=1)
        else:
            break

    breakdown = []
    for muscle in MUSCLE_GROUPS:
        ex_ids = await db[EX].distinct("_id", {"user_id": user_id, "muscle": muscle})
        if not ex_ids:
            breakdown.append(
                MuscleStats(muscle=muscle, total_sessions=0, total_sets=0, last_trained=None)
            )
            continue
        match = {"user_id": user_id, "exercise_id": {"$in": ex_ids}}
        m_sessions = await db[SE].count_documents(match)
        m_sets = await count_sets(match)
        last = await db[SE].find_one(match, sort=[("date", -1)])
        breakdown.append(
            MuscleStats(
                muscle=muscle,
                total_sessions=m_sessions,
                total_sets=m_sets,
                last_trained=last["date"] if last else None,
            )
        )

    return OverviewResponse(
        total_sessions=total_sessions,
        total_sets=total_sets,
        total_exercises=total_exercises,
        prs_this_month=prs,
        current_streak=streak,
        muscle_breakdown=breakdown,
    )


async def test_overview_matches_old_reference(db):
    uid = ObjectId()
    bench, row, squat = ObjectId(), ObjectId(), ObjectId()
    today = now_utc().date()
    before = today.replace(day=1) - timedelta(days=10)  # firmly in the previous month

    def s(ex, d, *weights):
        return {"user_id": uid, "exercise_id": ex, "date": _at(d), "sets": _sets(*weights)}

    exercises = [
        (bench, {"muscle": "chest", "name": "Bench", "emoji": "🏋️", "image_url": None, "created_at": _at(before)}),
        (row, {"muscle": "back", "name": "Row", "emoji": "🏋️", "image_url": None, "created_at": _at(before)}),
        (squat, {"muscle": "legs", "name": "Squat", "emoji": "🦵", "image_url": None, "created_at": _at(before)}),
    ]
    sessions = [
        s(bench, before, 60, 62),                       # prev PR 62
        s(bench, today, 70),                            # new PR this month; trains today
        s(bench, today - timedelta(days=1), 68),        # consecutive day
        s(row, before, 80),                             # prev PR 80
        s(row, today, 75),                              # no PR
        s(squat, before, 100),                          # prev PR 100
        s(squat, today - timedelta(days=2), 110),       # new PR this month, but a day gap
    ]
    await _insert(db, uid, exercises, sessions)

    new = await progress_service.get_overview(db, uid)
    old = await _old_overview(db, uid)
    assert new == old


async def test_overview_edge_cases(db, monkeypatch):
    # Freeze "now" so the month boundary and streak are deterministic.
    fixed_now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(progress_service, "now_utc", lambda: fixed_now)
    today = fixed_now.date()

    uid = ObjectId()
    newbie, idle = ObjectId(), ObjectId()

    def s(ex, d, *weights):
        return {"user_id": uid, "exercise_id": ex, "date": _at(d), "sets": _sets(*weights)}

    exercises = [
        # newbie: trained only this month -> PR up from zero.
        (newbie, {"muscle": "chest", "name": "Incline", "emoji": "🏋️", "image_url": None, "created_at": _at(today)}),
        # idle: an exercise with no sessions at all.
        (idle, {"muscle": "back", "name": "Pullup", "emoji": "🏋️", "image_url": None, "created_at": _at(today)}),
    ]
    sessions = [
        s(newbie, today, 40, 45),                 # 2 sets, trains today
        s(newbie, today - timedelta(days=1), 42),  # 1 set, consecutive day
    ]
    await _insert(db, uid, exercises, sessions)

    ov = await progress_service.get_overview(db, uid)

    assert ov.total_sessions == 2
    assert ov.total_sets == 3            # 2 + 1
    assert ov.total_exercises == 2
    assert ov.prs_this_month == 1        # newbie counts; idle has no sessions
    assert ov.current_streak == 2        # today + yesterday

    # All 8 muscle groups present, in order, with zeros/None for untrained ones.
    assert [m.muscle for m in ov.muscle_breakdown] == MUSCLE_GROUPS
    by_muscle = {m.muscle: m for m in ov.muscle_breakdown}
    chest = by_muscle["chest"]
    assert (chest.total_sessions, chest.total_sets) == (2, 3)
    assert chest.last_trained == _at(today)
    back = by_muscle["back"]             # idle exercise, no sessions
    assert (back.total_sessions, back.total_sets, back.last_trained) == (0, 0, None)
    legs = by_muscle["legs"]             # no exercises at all
    assert (legs.total_sessions, legs.total_sets, legs.last_trained) == (0, 0, None)
