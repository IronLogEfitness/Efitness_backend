"""Shared rate limiter (slowapi).

Defined in its own module so both the composition root (``app.create_app``, which
registers ``app.state.limiter`` and the 429 handler) and the auth router (which
decorates its endpoints) import the *same* ``Limiter`` instance.

Requests are keyed by client IP. The limit value is read from settings at call
time via ``auth_rate_limit`` (a callable), so it stays configurable and can be
relaxed or disabled in tests.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(key_func=get_remote_address)


def auth_rate_limit(*_args) -> str:
    """The per-IP limit for the auth endpoints (e.g. ``"10/minute"``)."""
    return settings.AUTH_RATE_LIMIT
