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
