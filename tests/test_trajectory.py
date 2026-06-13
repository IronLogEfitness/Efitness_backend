"""Goal trajectory maths (Feature 7) — pure projection."""
from datetime import datetime, timedelta, timezone

from app.goals.service import compute_trajectory

NOW = datetime(2026, 6, 13, tzinfo=timezone.utc)


def _pt(days_offset, weight):
    return {"date": NOW + timedelta(days=days_offset), "max_weight": weight}


def test_no_history_is_no_data():
    out = compute_trajectory([], target_value=80, target_date=NOW + timedelta(days=30), now=NOW)
    assert out["status"] == "no_data"
    assert out["on_track"] is False
    assert out["current_best"] is None


def test_already_achieved():
    history = [_pt(-30, 70), _pt(0, 85)]
    out = compute_trajectory(history, target_value=80, target_date=NOW + timedelta(days=30), now=NOW)
    assert out["status"] == "achieved"
    assert out["on_track"] is True
    assert out["current_best"] == 85


def test_on_track_projection():
    # +10kg over 30 days → 0.333kg/day; 30 days left → projects 70+10 = 80 ≥ 80.
    history = [_pt(-30, 60), _pt(0, 70)]
    out = compute_trajectory(history, target_value=80, target_date=NOW + timedelta(days=30), now=NOW)
    assert out["status"] == "on_track"
    assert out["on_track"] is True
    assert out["projected_value"] == 80.0
    assert out["days_remaining"] == 30


def test_off_track_projection():
    history = [_pt(-30, 60), _pt(0, 70)]
    out = compute_trajectory(history, target_value=90, target_date=NOW + timedelta(days=30), now=NOW)
    assert out["status"] == "off_track"
    assert out["on_track"] is False
    assert out["projected_value"] == 80.0


def test_flat_progress_is_off_track():
    history = [_pt(-30, 70), _pt(0, 70)]
    out = compute_trajectory(history, target_value=80, target_date=NOW + timedelta(days=30), now=NOW)
    assert out["slope_per_week"] == 0.0
    assert out["status"] == "off_track"


def test_single_point_has_zero_slope():
    history = [_pt(0, 75)]
    out = compute_trajectory(history, target_value=80, target_date=NOW + timedelta(days=30), now=NOW)
    assert out["slope_per_week"] == 0.0
    assert out["current"] == 75
