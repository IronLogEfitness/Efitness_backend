"""ID-resolution helpers — pure date parsing + fuzzy matching."""
from datetime import date, datetime, timezone

from app.coach.resolve import _pick, fuzzy_match, parse_date_ref

TODAY = date(2026, 6, 13)


def test_parse_today():
    assert parse_date_ref("today", today=TODAY) == datetime(2026, 6, 13, tzinfo=timezone.utc)


def test_parse_tomorrow_and_yesterday():
    assert parse_date_ref("tomorrow", today=TODAY) == datetime(2026, 6, 14, tzinfo=timezone.utc)
    assert parse_date_ref("yesterday", today=TODAY) == datetime(2026, 6, 12, tzinfo=timezone.utc)


def test_parse_iso_date():
    assert parse_date_ref("2026-08-01") == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_case_and_whitespace_insensitive():
    assert parse_date_ref("  Today ", today=TODAY) == datetime(2026, 6, 13, tzinfo=timezone.utc)


def test_non_date_returns_none():
    assert parse_date_ref("next tuesday") is None
    assert parse_date_ref("Push day") is None
    assert parse_date_ref("2026-13-99") is None  # invalid calendar date
    assert parse_date_ref(None) is None


def test_fuzzy_exact_match_wins():
    ranked = fuzzy_match("Bench Press", ["Squat", "Bench Press", "Deadlift"])
    assert ranked[0][0] == "Bench Press"
    assert ranked[0][1] == 1.0


def test_fuzzy_substring_scores_high():
    ranked = fuzzy_match("bench", ["Bench Press", "Squat"])
    assert ranked[0][0] == "Bench Press"
    assert ranked[0][1] >= 0.9


def test_pick_confident_single_match():
    winner, close = _pick(fuzzy_match("Bench Press", ["Bench Press", "Squat"]))
    assert winner == "Bench Press"


def test_pick_ambiguous_returns_no_winner():
    # "bench" is a substring of both → both score 0.9 → ambiguous, ask the user.
    winner, close = _pick(fuzzy_match("bench", ["Bench Press", "Incline Bench Press"]))
    assert winner is None
    assert set(close) == {"Bench Press", "Incline Bench Press"}


def test_pick_no_candidates():
    assert _pick([]) == (None, [])
