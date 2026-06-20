"""Search the bundled exercise library, filtered/ranked by muscle group.

This mirrors the client's local `searchExercises` (IronLog
src/data/exerciseLibrary.ts) one-for-one, so an online (API) result and the
app's offline fallback rank identically. The dataset is the public-domain
free-exercise-db (https://github.com/yuhonas/free-exercise-db, Unlicense).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from app.muscles.constants import MUSCLE_MAP

_DATA_PATH = Path(__file__).parent / "data" / "exercise_library.json"


@lru_cache(maxsize=1)
def _library() -> list[dict]:
    """Load and cache the dataset once per process."""
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def _matches_muscle(exercise: dict, muscle: str | None) -> bool:
    if not muscle:
        return False
    if muscle == "cardio":
        return exercise.get("category") == "cardio"
    targets = MUSCLE_MAP.get(muscle)
    if not targets:
        return False
    return any(m in targets for m in exercise.get("muscles", []))


def search(query: str, muscle: str | None, limit: int = 30) -> list[dict]:
    """Search the library by name, favouring `muscle`.

    With an empty query, returns the exercises for the muscle group as sensible
    defaults (so picking "chest" immediately shows chest exercises, no legs).
    With a query, every term must appear in the name; results are scored by how
    exactly the query matches and whether the muscle group lines up.
    """
    library = _library()
    q = _norm(query or "")

    if not q:
        for_muscle = [e for e in library if _matches_muscle(e, muscle)]
        return for_muscle[:limit]

    terms = [t for t in q.split(" ") if t]
    scored: list[tuple[float, dict]] = []

    for ex in library:
        name = _norm(ex["name"])
        if not all(t in name for t in terms):  # every term must appear
            continue
        score = 0.0
        if name == q:
            score += 100
        if name.startswith(q):
            score += 50
        if q in name:  # contiguous phrase match
            score += 20
        if _matches_muscle(ex, muscle):
            score += 10
        score -= len(name) * 0.01  # gently prefer shorter, more exact names
        scored.append((score, ex))

    scored.sort(key=lambda s: s[0], reverse=True)
    return [ex for _, ex in scored[:limit]]
