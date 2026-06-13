"""Progressive-overload rule (Feature 2) — pure logic."""
from app.coach.progression import compute_progression


def test_all_sets_hit_increases_weight():
    sets = [{"weight_kg": 60, "reps": 10} for _ in range(3)]
    out = compute_progression(sets)
    assert out["action"] == "increase_weight"
    assert out["current_weight"] == 60
    assert out["suggested_weight"] == 62.5
    assert out["target_reps"] == 10


def test_missed_reps_holds_weight():
    sets = [{"weight_kg": 60, "reps": 10}, {"weight_kg": 60, "reps": 8}]
    out = compute_progression(sets)
    assert out["action"] == "hold"
    assert out["suggested_weight"] == 60


def test_explicit_target_reps():
    sets = [{"weight_kg": 60, "reps": 8} for _ in range(3)]
    out = compute_progression(sets, target_reps=8)
    assert out["action"] == "increase_weight"
    assert out["suggested_weight"] == 62.5


def test_warmup_sets_are_ignored():
    # 40kg warm-up should not block progression evaluated on the 60kg top sets.
    sets = [
        {"weight_kg": 40, "reps": 12},
        {"weight_kg": 60, "reps": 10},
        {"weight_kg": 60, "reps": 10},
    ]
    out = compute_progression(sets)
    assert out["action"] == "increase_weight"
    assert out["current_weight"] == 60
    assert out["suggested_weight"] == 62.5


def test_bodyweight_adds_reps_not_load():
    sets = [{"weight_kg": 0, "reps": 12} for _ in range(3)]
    out = compute_progression(sets)
    assert out["action"] == "add_reps"
    assert out["current_weight"] == 0
    assert out["suggested_weight"] == 0
    assert out["target_reps"] == 13


def test_no_history_is_baseline():
    out = compute_progression([])
    assert out["action"] == "baseline"
    assert out["suggested_weight"] is None


def test_custom_increment():
    sets = [{"weight_kg": 100, "reps": 5} for _ in range(3)]
    out = compute_progression(sets, increment_kg=5)
    assert out["suggested_weight"] == 105
