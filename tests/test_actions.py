"""Write-tool validation, proposal building, and execution ordering — pure parts.

The DB-bound idempotency state machine (pending → executing → executed) is verified
manually against MongoDB; here we cover the logic that needs no DB: arg validation,
the model-call → Action conversion, action_id minting, and dependency-safe ordering.
"""
from types import SimpleNamespace

import pytest

from app.coach import execute, tools
from app.coach.agent import _to_action


# ── validate_write ──
def test_validate_log_sets_ok():
    args, summary = tools.validate_write(
        "log_sets",
        {
            "exercise_ref": "Bench Press",
            "sets": [{"set_number": 1, "weight_kg": 60, "reps": 10}],
        },
    )
    assert args["exercise_ref"] == "Bench Press"
    assert args["workout_ref"] == "today"  # default applied
    assert "Bench Press" in summary
    assert "60kg×10" in summary


def test_validate_log_sets_rejects_zero_reps():
    with pytest.raises(Exception):
        tools.validate_write(
            "log_sets",
            {"exercise_ref": "Squat", "sets": [{"set_number": 1, "weight_kg": 80, "reps": 0}]},
        )


def test_validate_log_sets_allows_bodyweight_zero():
    args, _ = tools.validate_write(
        "log_sets",
        {"exercise_ref": "Pull Up", "sets": [{"set_number": 1, "weight_kg": 0, "reps": 8}]},
    )
    assert args["sets"][0]["weight_kg"] == 0


def test_validate_create_goal_rejects_nonpositive_target():
    with pytest.raises(Exception):
        tools.validate_write("create_goal", {"target_value": 0, "target_date": "2026-08-01"})


def test_validate_update_goal_requires_a_field():
    with pytest.raises(Exception):
        tools.validate_write("update_goal", {"goal_id": "abc123"})


def test_create_workout_summary():
    _, summary = tools.validate_write("create_workout", {"date": "today", "title": "Push"})
    assert "Push" in summary


# ── _to_action (model call → proposal) ──
def test_to_action_builds_pending_proposal():
    call = SimpleNamespace(
        name="log_sets",
        args={"exercise_ref": "Bench Press", "sets": [{"set_number": 1, "weight_kg": 60, "reps": 10}]},
    )
    action = _to_action(call)
    assert action.type == "log_sets"
    assert action.status == "pending"
    assert action.needs_clarification is False
    assert len(action.action_id) == 32  # uuid4 hex


def test_to_action_invalid_args_needs_clarification():
    call = SimpleNamespace(name="log_sets", args={"sets": []})  # missing exercise_ref, empty sets
    action = _to_action(call)
    assert action.needs_clarification is True
    assert action.status == "needs_clarification"
    assert action.clarification


def test_action_ids_are_unique():
    call = SimpleNamespace(name="create_workout", args={"date": "today", "title": "Pull"})
    a1 = _to_action(call)
    a2 = _to_action(call)
    assert a1.action_id != a2.action_id


# ── execution ordering (dependency-safe) ──
def test_creates_run_before_dependents():
    proposed = ["log_sets", "create_workout", "add_muscle_group", "create_exercise"]
    ordered = sorted(proposed, key=lambda t: execute.EXECUTION_ORDER[t])
    # workout/exercise creation must precede add_muscle_group and log_sets
    assert ordered.index("create_workout") < ordered.index("log_sets")
    assert ordered.index("create_exercise") < ordered.index("log_sets")
    assert ordered.index("create_workout") < ordered.index("add_muscle_group")


def test_every_write_tool_has_an_execution_order_and_handler():
    for name in tools.WRITE_TOOL_NAMES:
        assert name in execute.EXECUTION_ORDER, name
        assert name in execute._HANDLERS, name
