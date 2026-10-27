"""Test bootstrap.

Most tests cover the coach's DETERMINISTIC core — pure functions that take plain
dicts/values — so they need no MongoDB connection and no Gemini API key. The
``db`` fixture adds an in-memory Mongo (mongomock-motor) for the DB-backed tests
(aggregation parity, data-layer flows); its import is lazy so the pure-logic
tests still run without the dev-only dependency installed.

We make sure the repo root is importable so ``import app...`` resolves when pytest
is invoked from anywhere.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def db():
    """A fresh, isolated in-memory Mongo database per test.

    Configured with ``tz_aware=True`` to mirror the production motor client
    (app.core.database.connect_db), so UTC-stored dates read back timezone-aware
    and aggregation date comparisons behave exactly as they do against real Mongo.
    """
    from mongomock_motor import AsyncMongoMockClient

    return AsyncMongoMockClient(tz_aware=True)["ironlog_test"]
