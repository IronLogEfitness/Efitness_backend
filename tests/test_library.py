"""Exercise-library search/filter — pure logic over the bundled dataset."""
from app.library import service
from app.muscles.constants import MUSCLE_GROUPS, MUSCLE_MAP


def test_dataset_loads():
    lib = service._library()
    assert isinstance(lib, list) and len(lib) > 0
    assert {"id", "name", "muscles"} <= set(lib[0].keys())


def test_muscle_map_covers_every_group():
    assert set(MUSCLE_MAP) == set(MUSCLE_GROUPS)


def test_empty_query_returns_only_that_muscle():
    results = service.search("", "chest", limit=50)
    assert results, "expected default chest exercises"
    for ex in results:
        assert any(m in MUSCLE_MAP["chest"] for m in ex["muscles"])
    # No leg muscles leak into a chest request.
    leg_muscles = set(MUSCLE_MAP["legs"])
    for ex in results:
        assert not (set(ex["muscles"]) & leg_muscles)


def test_limit_is_respected():
    assert len(service.search("", "legs", limit=5)) == 5


def test_query_requires_every_term_in_name():
    for ex in service.search("bench press", "chest", limit=20):
        name = ex["name"].lower()
        assert "bench" in name and "press" in name


def test_query_ranks_matching_muscle_first():
    # A canonical chest movement under "chest" puts a chest exercise on top.
    top = service.search("bench press", "chest", limit=1)
    assert top and any(m in MUSCLE_MAP["chest"] for m in top[0]["muscles"])


def test_cardio_matches_by_category():
    for ex in service.search("", "cardio", limit=10):
        assert ex.get("category") == "cardio"


def test_unknown_muscle_empty_query_returns_nothing():
    assert service.search("", "not-a-muscle", limit=10) == []
