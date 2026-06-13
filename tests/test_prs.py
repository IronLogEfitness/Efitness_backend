"""PR detection (Feature 3) — pure logic."""
from app.coach.prs import detect_pr


def test_new_pr_beats_previous_best():
    badge = detect_pr([{"weight_kg": 60, "reps": 5}], previous_best=50)
    assert badge == {"is_pr": True, "value": 60, "prev_best": 50}


def test_no_pr_when_below_previous_best():
    assert detect_pr([{"weight_kg": 50, "reps": 8}], previous_best=60) is None


def test_tie_is_not_a_pr():
    assert detect_pr([{"weight_kg": 60, "reps": 3}], previous_best=60) is None


def test_first_ever_lift_is_a_pr():
    badge = detect_pr([{"weight_kg": 40, "reps": 10}], previous_best=None)
    assert badge["is_pr"] is True
    assert badge["value"] == 40
    assert badge["prev_best"] is None


def test_first_ever_bodyweight_is_not_a_pr():
    assert detect_pr([{"weight_kg": 0, "reps": 15}], previous_best=None) is None


def test_best_set_in_a_mixed_session_counts():
    badge = detect_pr(
        [{"weight_kg": 50, "reps": 8}, {"weight_kg": 65, "reps": 3}], previous_best=60
    )
    assert badge["value"] == 65


def test_empty_sets_returns_none():
    assert detect_pr([], previous_best=10) is None
