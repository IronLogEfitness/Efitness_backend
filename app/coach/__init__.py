"""The agentic coach layer.

Turns the read-only chat coach into one that can *act* on the user's training
app via Gemini function calling, under a strict human-in-the-loop rule: write
tools are never auto-executed — they are returned from ``POST /chat`` as
``proposed_actions`` and only run after the user confirms them via
``POST /chat/confirm`` (see ``agent`` and ``actions``).

Deterministic work (PR detection, progression maths, muscle-balance ratios,
recap/briefing aggregation) lives in plain code (``prs``, ``progression``,
``balance``, ``recap``, ``briefing``) so it spends zero Gemini quota. Gemini is
called only for open-ended reasoning (NL parsing, planning) and optional phrasing.
"""
