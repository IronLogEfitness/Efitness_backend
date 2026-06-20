"""Read-only exercise library.

Serves the bundled free-exercise-db dataset, filtered by muscle group, so the
client picker shows only relevant exercises (e.g. chest → only chest). The
backend is the source of truth; the mobile app keeps a local copy only as an
offline fallback.
"""
