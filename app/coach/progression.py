"""Feature 2 — progressive-overload autopilot.

Deterministic double-progression rule applied to the last session's sets for one
exercise. No Gemini call is required; the suggestion is phrased from a template.

Rule (evaluated on the *top working set group* — the sets at the heaviest weight,
so warm-up / ramp sets don't block progress):
  - All top sets hit the target reps  → add weight (or, for bodyweight, add a rep).
  - Any top set fell short             → hold the weight and repeat.

``compute_progression`` is pure (plain dicts in, dict out) so it is unit-testable
without a DB and reusable from ``coach.router`` (GET /coach/progression).
"""

DEFAULT_INCREMENT_KG = 2.5


def compute_progression(
    last_sets: list[dict],
    target_reps: int | None = None,
    increment_kg: float = DEFAULT_INCREMENT_KG,
) -> dict:
    """Suggest next-session targets for one exercise from its last session.

    ``last_sets``    — the most recent session's sets (``{"weight_kg", "reps"}``).
    ``target_reps``  — explicit rep target; when omitted, defaults to the best rep
                       count among the top working sets (so "all hit" means every
                       top set matched the best one — i.e. consistent performance).

    Returns a dict: ``action`` in
    ``{"baseline", "increase_weight", "add_reps", "hold"}`` plus
    ``current_weight``, ``suggested_weight``, ``target_reps`` and a templated
    ``reason``.
    """
    if not last_sets:
        return {
            "action": "baseline",
            "current_weight": None,
            "suggested_weight": None,
            "target_reps": target_reps,
            "reason": "No history yet — log a baseline session to start progressing.",
        }

    working_weight = max(s["weight_kg"] for s in last_sets)
    top_sets = [s for s in last_sets if s["weight_kg"] == working_weight]
    target = target_reps if target_reps is not None else max(s["reps"] for s in top_sets)
    all_hit = min(s["reps"] for s in top_sets) >= target

    if not all_hit:
        return {
            "action": "hold",
            "current_weight": working_weight,
            "suggested_weight": working_weight,
            "target_reps": target,
            "reason": (
                f"Last time you missed {target} reps on some sets at {working_weight}kg "
                f"— repeat {working_weight}kg and aim for {target} across all sets."
            ),
        }

    if working_weight == 0:  # bodyweight: progress reps, not load
        return {
            "action": "add_reps",
            "current_weight": 0,
            "suggested_weight": 0,
            "target_reps": target + 1,
            "reason": (
                f"All sets hit {target} reps bodyweight — push for {target + 1} reps next time."
            ),
        }

    suggested = round(working_weight + increment_kg, 1)
    return {
        "action": "increase_weight",
        "current_weight": working_weight,
        "suggested_weight": suggested,
        "target_reps": target,
        "reason": (
            f"All {len(top_sets)} top set(s) hit {target}+ reps at {working_weight}kg "
            f"— add {increment_kg}kg and go for {suggested}kg."
        ),
    }


# ── DB-backed reader (GET /coach/progression) ──
async def build_progression(db, user_id, workout_ref: str):
    """Next-session targets for every exercise logged in one workout.

    Resolves the workout, takes each exercise's most recent set-log *within that
    workout* as the "last session", and applies ``compute_progression``. Returns a
    ``ProgressionResponse``. Kept separate from the pure rule above so the maths
    stays unit-testable without a DB.
    """
    from app.coach import resolve
    from app.coach.schemas import ProgressionItem, ProgressionResponse
    from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
    from app.sessions.models import COLLECTION as SESSIONS_COLLECTION

    wid, _ = await resolve.resolve_workout(db, user_id, workout_ref, create=False)

    logs = await (
        db[SESSIONS_COLLECTION]
        .find({"user_id": user_id, "workout_id": wid})
        .sort("date", 1)
        .to_list(length=300)
    )
    # Keep each exercise's latest set-log in this workout (ascending sort → last wins).
    latest: dict = {}
    for s in logs:
        latest[s["exercise_id"]] = s

    items: list[ProgressionItem] = []
    for ex_id, s in latest.items():
        ex = await db[EXERCISES_COLLECTION].find_one({"_id": ex_id, "user_id": user_id})
        items.append(
            ProgressionItem(
                exercise_id=str(ex_id),
                exercise_name=ex["name"] if ex else "Unknown",
                **compute_progression(s["sets"]),
            )
        )
    return ProgressionResponse(workout_id=str(wid), items=items)
