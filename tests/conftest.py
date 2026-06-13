"""Test bootstrap.

These tests cover the coach's DETERMINISTIC core only — pure functions that take
plain dicts/values — so they need no MongoDB connection and no Gemini API key.
We make sure the repo root is importable so ``import app...`` resolves when pytest
is invoked from anywhere.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
