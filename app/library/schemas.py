"""Response model for the exercise-library endpoint.

The shape mirrors one entry of the bundled free-exercise-db JSON exactly, so the
client can treat an API result and its local offline copy identically.
"""
from pydantic import BaseModel


class LibraryExercise(BaseModel):
    id: str
    name: str
    equipment: str | None = None
    category: str | None = None
    muscles: list[str] = []
    # Relative image path within the free-exercise-db `exercises/` folder, e.g.
    # "Barbell_Bench_Press_-_Medium_Grip/0.jpg". The client builds the full CDN
    # URL from it (so the CDN base lives in one place on the client).
    img: str | None = None
