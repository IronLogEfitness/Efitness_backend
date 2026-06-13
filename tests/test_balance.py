"""Muscle-balance audit (Feature 4) — pure logic."""
from app.coach.balance import audit_balance


def _bd(**sets):
    """Build a muscle_breakdown list from muscle=sets kwargs."""
    return [{"muscle": m, "total_sets": n} for m, n in sets.items()]


def test_balanced_program_has_no_imbalances():
    out = audit_balance(_bd(chest=10, back=10, legs=8))
    assert out["balanced"] is True
    assert out["imbalances"] == []
    assert out["push_sets"] == 10
    assert out["pull_sets"] == 10
    assert out["legs_sets"] == 8


def test_push_dominant_flags_and_suggests_pull():
    out = audit_balance(_bd(chest=20, back=5, biceps=3, legs=10))
    types = {i["type"] for i in out["imbalances"]}
    assert "push_dominant" in types
    push_flag = next(i for i in out["imbalances"] if i["type"] == "push_dominant")
    assert set(push_flag["suggest_muscles"]) == {"back", "biceps"}
    assert out["push_pull_ratio"] == 2.5
    assert out["balanced"] is False


def test_no_pull_logged():
    out = audit_balance(_bd(chest=10, shoulders=4))
    types = {i["type"] for i in out["imbalances"]}
    assert "no_pull" in types
    assert out["push_pull_ratio"] is None  # no pull volume → undefined ratio


def test_legs_neglected():
    out = audit_balance(_bd(chest=12, back=12, legs=2))
    types = {i["type"] for i in out["imbalances"]}
    assert "legs_neglected" in types
    legs_flag = next(i for i in out["imbalances"] if i["type"] == "legs_neglected")
    assert legs_flag["suggest_muscles"] == ["legs"]


def test_abs_and_cardio_do_not_affect_balance():
    out = audit_balance(_bd(chest=10, back=10, legs=8, abs=30, cardio=50))
    assert out["balanced"] is True
