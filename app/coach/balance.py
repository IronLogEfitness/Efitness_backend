"""Feature 4 — muscle-balance auditor.

Deterministic push/pull/legs volume audit over the per-muscle set counts already
computed by ``progress.get_overview``. No Gemini call: the maths is pure code; the
model only *frames* any corrective workout it proposes.

``audit_balance`` is pure (plain dicts in, dict out) so it is unit-testable and
reusable from both the ``get_muscle_balance`` read tool and GET /coach/balance.
"""

# Which muscles count toward each movement pattern. abs/cardio are tracked
# separately and don't take part in the push:pull:legs balance.
PUSH = ("chest", "shoulders", "triceps")
PULL = ("back", "biceps")
LEGS = ("legs",)

# A pattern is "dominant" when it carries at least this multiple of its counterpart.
DEFAULT_IMBALANCE_THRESHOLD = 1.5


def audit_balance(
    muscle_breakdown: list[dict],
    imbalance_threshold: float = DEFAULT_IMBALANCE_THRESHOLD,
) -> dict:
    """Audit training balance from a list of ``{"muscle", "total_sets"}`` rows.

    Returns push/pull/legs set totals, the push:pull ratio, a list of
    ``imbalances`` (each ``{"type", "message", "suggest_muscles"}``) and a
    ``balanced`` flag. Each imbalance names the muscles to add more of, which the
    caller can turn into a corrective-workout proposal.
    """
    sets = {m["muscle"]: m.get("total_sets", 0) for m in muscle_breakdown}
    push = sum(sets.get(m, 0) for m in PUSH)
    pull = sum(sets.get(m, 0) for m in PULL)
    legs = sum(sets.get(m, 0) for m in LEGS)

    imbalances: list[dict] = []

    # ── Push vs pull ──
    if push and pull:
        if push >= pull * imbalance_threshold:
            imbalances.append({
                "type": "push_dominant",
                "message": f"Push volume ({push} sets) far outweighs pull ({pull} sets).",
                "suggest_muscles": list(PULL),
            })
        elif pull >= push * imbalance_threshold:
            imbalances.append({
                "type": "pull_dominant",
                "message": f"Pull volume ({pull} sets) far outweighs push ({push} sets).",
                "suggest_muscles": list(PUSH),
            })
    elif push and not pull:
        imbalances.append({
            "type": "no_pull",
            "message": f"You've trained push ({push} sets) but logged no pull work.",
            "suggest_muscles": list(PULL),
        })
    elif pull and not push:
        imbalances.append({
            "type": "no_push",
            "message": f"You've trained pull ({pull} sets) but logged no push work.",
            "suggest_muscles": list(PUSH),
        })

    # ── Legs vs upper body ── flag when legs carry less than a third of upper volume.
    upper = push + pull
    if upper and legs * 3 < upper:
        imbalances.append({
            "type": "legs_neglected",
            "message": f"Legs ({legs} sets) lag well behind upper-body volume ({upper} sets).",
            "suggest_muscles": list(LEGS),
        })

    return {
        "push_sets": push,
        "pull_sets": pull,
        "legs_sets": legs,
        "push_pull_ratio": round(push / pull, 2) if pull else None,
        "imbalances": imbalances,
        "balanced": not imbalances,
    }
