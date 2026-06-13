"""Feature 3 — PR (personal-record) detection.

Deterministic: a set is a PR when its weight beats the heaviest weight ever
lifted for that exercise *before* this set was logged. No Gemini call — the
celebration copy is templated by the caller.

``detect_pr`` is a pure function over plain dicts so it is trivially unit-testable
and reusable from both the manual log path (``sessions.service.create_session``)
and the agentic ``log_sets`` confirm path (``coach.execute``).
"""


def detect_pr(new_sets: list[dict], previous_best: float | None) -> dict | None:
    """Return a PR badge dict if any set in ``new_sets`` beats ``previous_best``.

    ``new_sets``       — sets just logged, each ``{"weight_kg": float, "reps": int}``.
    ``previous_best``  — heaviest weight ever lifted for this exercise BEFORE these
                         sets (``None`` if this is the first session for it).

    Returns ``{"is_pr": True, "value": <kg>, "prev_best": <kg|None>}`` on a new PR,
    or ``None`` when nothing beat the previous best. A first-ever lift at >0 kg
    counts as a PR (``prev_best`` is ``None``); a first-ever bodyweight (0 kg) lift
    does not.
    """
    if not new_sets:
        return None

    best_now = max(s["weight_kg"] for s in new_sets)
    prev = previous_best or 0.0
    if best_now > prev:
        return {"is_pr": True, "value": best_now, "prev_best": previous_best}
    return None
