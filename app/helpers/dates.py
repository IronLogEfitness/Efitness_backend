from datetime import datetime, timezone


def now_utc() -> datetime:
    """Timezone-aware current UTC time.

    Replaces the deprecated ``datetime.utcnow()`` (which returned a naive value).
    """
    return datetime.now(timezone.utc)
