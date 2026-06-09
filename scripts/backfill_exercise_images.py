"""One-off migration: backfill `image_url` on a user's existing exercises by
matching their names against the bundled free-exercise-db library.

Dry-run by default (prints proposed changes, writes nothing). Pass --apply to
persist. Only fills exercises that currently have no image_url; picker-chosen
images are left untouched.

Usage (from the Efitness_backend dir):
    venv/Scripts/python.exe scripts/backfill_exercise_images.py
    venv/Scripts/python.exe scripts/backfill_exercise_images.py --apply
"""
import asyncio
import json
import re
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

# Allow running as `python scripts/backfill_exercise_images.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings

EMAIL = "rafik.gatri.2002@gmail.com"
LIBRARY_PATH = Path(r"C:\Users\rgatr\IronLog\src\data\exerciseLibrary.json")
IMAGE_BASE = "https://cdn.jsdelivr.net/gh/yuhonas/free-exercise-db@main/exercises/"

# Mirrors the app's muscle-group -> db primaryMuscles mapping so a chest
# exercise prefers a chest illustration when the name is ambiguous.
MUSCLE_MAP = {
    "chest": ["chest"],
    "back": ["lats", "middle back", "lower back", "traps", "neck"],
    "biceps": ["biceps", "forearms"],
    "triceps": ["triceps"],
    "legs": ["quadriceps", "hamstrings", "calves", "glutes", "adductors", "abductors"],
    "shoulders": ["shoulders"],
    "abs": ["abdominals"],
    "cardio": [],
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def matches_muscle(ex: dict, muscle: str | None) -> bool:
    if not muscle:
        return False
    if muscle == "cardio":
        return ex.get("category") == "cardio"
    targets = MUSCLE_MAP.get(muscle, [])
    return bool(targets) and any(m in targets for m in ex.get("muscles", []))


def best_match(name: str, muscle: str | None, library: list[dict]) -> dict | None:
    """Return the best library entry for an exercise name, or None.

    Every word of the query must appear in the candidate name; among those, we
    score exact/prefix/substring matches and the right muscle group, and prefer
    shorter names. Returns None when no candidate contains all query words.
    """
    q = norm(name)
    terms = [t for t in q.split(" ") if t]
    if not terms:
        return None

    best = None
    best_score = -1.0
    for ex in library:
        n = norm(ex["name"])
        if not all(t in n for t in terms):
            continue
        score = 0.0
        if n == q:
            score += 100
        if n.startswith(q):
            score += 50
        if q in n:
            score += 20
        if matches_muscle(ex, muscle):
            score += 10
        score -= len(n) * 0.01
        if score > best_score:
            best_score = score
            best = ex
    return best


async def main(apply: bool) -> None:
    library = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.DB_NAME]

    user = await db["users"].find_one({"email": EMAIL})
    if not user:
        print(f"User {EMAIL!r} not found. Existing emails:")
        async for u in db["users"].find({}, {"email": 1}):
            print("  -", u.get("email"))
        return

    exercises = await db["exercises"].find({"user_id": user["_id"]}).to_list(None)
    print(f"User {EMAIL} has {len(exercises)} exercises.\n")

    to_update: list[tuple[dict, str]] = []
    skipped_have_image = 0
    no_match = []

    for ex in exercises:
        name = ex["name"]
        muscle = ex.get("muscle")
        has_image = bool(ex.get("image_url"))
        match = best_match(name, muscle, library)
        proposed = IMAGE_BASE + match["img"] if match and match.get("img") else None

        if has_image:
            skipped_have_image += 1
            status = "SKIP (already has image)"
            matched_name = "—"
        elif not proposed:
            no_match.append(name)
            status = "NO MATCH"
            matched_name = "—"
        else:
            status = "WILL SET" if apply else "WOULD SET"
            matched_name = match["name"]
            to_update.append((ex, proposed))

        print(f"[{status}] {muscle:<10} {name!r}")
        if matched_name != "—":
            print(f"            -> {matched_name!r}")
            print(f"            -> {proposed}")

    print("\n--- Summary ---")
    print(f"  to set image:        {len(to_update)}")
    print(f"  already had image:   {skipped_have_image}")
    print(f"  no library match:    {len(no_match)}")
    if no_match:
        print("  unmatched names:", ", ".join(repr(n) for n in no_match))

    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to persist.")
        return

    print("\nApplying...")
    for ex, url in to_update:
        await db["exercises"].update_one(
            {"_id": ex["_id"]}, {"$set": {"image_url": url}}
        )
    print(f"Done. Updated {len(to_update)} exercises.")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
