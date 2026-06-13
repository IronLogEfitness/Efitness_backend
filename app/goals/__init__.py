"""Training goals (Feature 7).

A goal is a target the user is working toward — e.g. "bench 80 kg by August".
Stored in the ``goals`` collection and scoped to ``user_id``. The trajectory
endpoint computes pace **deterministically** from the user's exercise history
(current best, slope, days remaining → on/off track), so no Gemini call is needed
to tell the user whether they're on track.
"""
