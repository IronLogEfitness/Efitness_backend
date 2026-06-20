"""The fixed set of muscle groups an exercise can belong to.

Lives in the muscles domain because it is the source of truth for what a
"muscle" is; the exercises and progress features import it from here.
"""

MUSCLE_GROUPS = [
    "chest",
    "back",
    "biceps",
    "triceps",
    "legs",
    "shoulders",
    "abs",
    "cardio",
]

# Maps each app muscle group to the fine-grained `muscles` values used by the
# bundled free-exercise-db library. This is the "intelligent relation" that lets
# the library endpoint surface, say, only chest exercises when the user picks
# chest. `cardio` carries no muscles — it is matched on the library `category`
# instead (see app.library.service). Keep the keys in sync with MUSCLE_GROUPS.
MUSCLE_MAP: dict[str, list[str]] = {
    "chest": ["chest"],
    "back": ["lats", "middle back", "lower back", "traps", "neck"],
    "biceps": ["biceps", "forearms"],
    "triceps": ["triceps"],
    "legs": ["quadriceps", "hamstrings", "calves", "glutes", "adductors", "abductors"],
    "shoulders": ["shoulders"],
    "abs": ["abdominals"],
    "cardio": [],
}
