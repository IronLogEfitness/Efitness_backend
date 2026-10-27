"""Unit tests for the pure streak computation extracted from the overview
rewrite (app.progress.service.compute_streak).

The old implementation fired up to 365 per-day count queries; the streak logic
itself is now a pure function over the set of UTC days the user trained, so it
can be verified directly here with no DB.
"""
from datetime import date, timedelta

from app.progress.service import compute_streak

TODAY = date(2026, 10, 27)


def _days_back(*offsets):
    """Set of days at the given offsets (in days) before TODAY."""
    return {TODAY - timedelta(days=n) for n in offsets}


def test_empty_history_is_zero():
    assert compute_streak(set(), TODAY) == 0


def test_today_missing_breaks_immediately():
    # Trained yesterday and the day before, but not today -> streak 0.
    assert compute_streak(_days_back(1, 2, 3), TODAY) == 0


def test_single_day_today():
    assert compute_streak(_days_back(0), TODAY) == 1


def test_consecutive_days_including_today():
    assert compute_streak(_days_back(0, 1, 2, 3), TODAY) == 4


def test_gap_stops_the_count():
    # today, yesterday, then a gap (no day-2), then day-3 -> only 2 count.
    assert compute_streak(_days_back(0, 1, 3, 4), TODAY) == 2


def test_future_days_do_not_extend_streak():
    days = _days_back(0, 1) | {TODAY + timedelta(days=1)}
    assert compute_streak(days, TODAY) == 2


def test_capped_at_365():
    # 400 consecutive days including today; the cap mirrors the old range(365).
    days = {TODAY - timedelta(days=n) for n in range(400)}
    assert compute_streak(days, TODAY) == 365


def test_exactly_365_consecutive():
    days = {TODAY - timedelta(days=n) for n in range(365)}
    assert compute_streak(days, TODAY) == 365
