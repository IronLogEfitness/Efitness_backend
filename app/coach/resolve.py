"""ID resolution — turn the model's HUMAN references into real MongoDB ids.

The model must never invent ids (see the spec). Write tools carry human refs —
an exercise *name*, a *date* or "today", a workout *title* — and those are
resolved to real ids only here, at confirm time:

  - ``parse_date_ref`` / ``fuzzy_match`` are pure helpers (unit-tested, no DB).
  - ``resolve_exercise`` / ``resolve_workout`` query the user's own data and, when
    asked, create the missing row via the existing services (so a logged set lands
    in exactly the same place a manual one would).

When a reference is ambiguous or unresolvable, these raise ``NeedsClarification``
so the caller can ask one short question instead of guessing.
"""
import re
from datetime import UTC, datetime, time, timedelta
from difflib import SequenceMatcher

from bson import ObjectId

from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.muscles.constants import MUSCLE_GROUPS
from app.workouts.models import COLLECTION as WORKOUTS_COLLECTION

# How similar a name must be to count as a fuzzy match (0..1, SequenceMatcher).
FUZZY_THRESHOLD = 0.6
# A top match this much clearer than the runner-up is accepted without asking.
FUZZY_MARGIN = 0.15

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class NeedsClarification(Exception):
    """A human ref couldn't be resolved unambiguously; carries a question to ask."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


# ── Pure helpers (unit-tested without a DB) ──
def _midnight_utc(day) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def parse_date_ref(ref: str | None, today=None) -> datetime | None:
    """Resolve ``today``/``tomorrow``/``yesterday``/``YYYY-MM-DD`` to a midnight-UTC
    datetime (matching how workouts store ``date``). Returns ``None`` when ``ref``
    isn't a recognisable date — the caller may then treat it as a title."""
    today = today or now_utc().date()
    r = (ref or "").strip().lower()
    if r in ("today", "now"):
        return _midnight_utc(today)
    if r == "tomorrow":
        return _midnight_utc(today + timedelta(days=1))
    if r == "yesterday":
        return _midnight_utc(today - timedelta(days=1))
    if _ISO_DATE.match(r):
        try:
            return _midnight_utc(datetime.strptime(r, "%Y-%m-%d").date())
        except ValueError:
            return None
    return None


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def fuzzy_match(name: str, candidates: list[str]) -> list[tuple[str, float]]:
    """Rank ``candidates`` by similarity to ``name``, best first.

    Exact (normalised) match scores 1.0; a substring relationship scores 0.9;
    otherwise the ``SequenceMatcher`` ratio. Returns ``[(candidate, score), …]``.
    """
    target = _norm(name)
    ranked: list[tuple[str, float]] = []
    for c in candidates:
        cn = _norm(c)
        if cn == target and target:
            score = 1.0
        elif target and (target in cn or cn in target):
            score = 0.9
        else:
            score = SequenceMatcher(None, target, cn).ratio()
        ranked.append((c, score))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def _pick(ranked: list[tuple[str, float]]) -> tuple[str | None, list[str]]:
    """From a ranked list decide a confident single match, else the close field.

    Returns ``(winner_or_None, close_candidates)``. A winner is returned when the
    top score is essentially exact, or it clears the threshold and is clearly
    ahead of the runner-up. Otherwise ``close_candidates`` lists what to ask about.
    """
    if not ranked:
        return None, []
    top_name, top_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    close = [n for n, s in ranked if s >= FUZZY_THRESHOLD]
    if top_score >= 0.99:
        return top_name, close
    if top_score >= FUZZY_THRESHOLD and (top_score - second >= FUZZY_MARGIN or len(close) == 1):
        return top_name, close
    return None, close


# ── DB resolvers ──
async def resolve_exercise(
    db, user_id: ObjectId, name: str, muscle_hint: str | None = None, create: bool = True
) -> tuple[ObjectId, bool]:
    """Resolve an exercise by name (optionally within ``muscle_hint``).

    Returns ``(exercise_id, created)``. Fuzzy-matches the user's own exercises;
    creates a new one (via ``exercises.service``) when there's no match and a valid
    muscle is known. Raises ``NeedsClarification`` on ambiguity or when creation
    isn't possible.
    """
    query: dict = {"user_id": user_id}
    if muscle_hint:
        query["muscle"] = muscle_hint.lower()
    exercises = await db[EXERCISES_COLLECTION].find(query).to_list(length=500)

    if exercises:
        winner, close = _pick(fuzzy_match(name, [e["name"] for e in exercises]))
        if winner is not None:
            match = next(e for e in exercises if e["name"] == winner)
            return match["_id"], False
        if len(close) > 1:
            raise NeedsClarification(
                f"Which exercise did you mean: {', '.join(close[:4])}?"
            )

    # No confident match → create it if we can.
    if not create:
        raise NeedsClarification(f"I couldn't find an exercise called '{name}'.")
    if not muscle_hint:
        raise NeedsClarification(
            f"I don't have an exercise called '{name}'. Which muscle group is it "
            f"(e.g. chest, back, legs)?"
        )
    if muscle_hint.lower() not in MUSCLE_GROUPS:
        raise NeedsClarification(
            f"'{muscle_hint}' isn't a known muscle group. Choose from: {MUSCLE_GROUPS}."
        )

    # Import here to avoid an import cycle at module load.
    from app.exercises.schemas import ExerciseCreate
    from app.exercises.service import create_exercise

    created = await create_exercise(
        db, user_id, ExerciseCreate(muscle=muscle_hint.lower(), name=name.strip())
    )
    return ObjectId(created["id"]), True


async def resolve_workout(
    db, user_id: ObjectId, ref: str, title: str | None = None, create: bool = True
) -> tuple[ObjectId, bool]:
    """Resolve a workout by date/"today" or by title.

    Returns ``(workout_id, created)``. For a date ref, finds that day's workout
    (preferring a title match) and creates one when asked; for a title ref, searches
    recent workouts. Raises ``NeedsClarification`` when nothing/too much matches.
    """
    day = parse_date_ref(ref)
    if day is not None:
        end = day + timedelta(days=1) - timedelta(microseconds=1)
        existing = await (
            db[WORKOUTS_COLLECTION]
            .find({"user_id": user_id, "date": {"$gte": day, "$lte": end}})
            .sort("date", 1)
            .to_list(length=20)
        )
        if title:
            tnorm = _norm(title)
            for w in existing:
                if _norm(w["title"]) == tnorm:
                    return w["_id"], False
        if existing:
            return existing[0]["_id"], False
        if not create:
            raise NeedsClarification(f"You have no workout logged on {ref}.")

        from app.workouts.schemas import WorkoutCreate
        from app.workouts.service import create_workout

        created = await create_workout(
            db, user_id, WorkoutCreate(date=day.date(), title=(title or "Workout"))
        )
        return ObjectId(created.id), True

    # ref is a title — search recent workouts.
    recent = await (
        db[WORKOUTS_COLLECTION]
        .find({"user_id": user_id})
        .sort("date", -1)
        .to_list(length=100)
    )
    tnorm = _norm(ref)
    matches = [w for w in recent if _norm(w["title"]) == tnorm]
    if not matches and recent:
        winner, _ = _pick(fuzzy_match(ref, [w["title"] for w in recent]))
        if winner is not None:
            matches = [w for w in recent if w["title"] == winner]

    if len(matches) == 1:
        return matches[0]["_id"], False
    if len(matches) > 1:
        raise NeedsClarification(
            f"You have several workouts titled like '{ref}'. Which date (e.g. 2026-06-13)?"
        )
    raise NeedsClarification(
        f"I couldn't find a workout matching '{ref}'. Give me a date like 'today' "
        f"or 2026-06-13."
    )
