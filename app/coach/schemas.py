"""Request / response models for the agentic coach.

Two families live here:
  - the propose → confirm contract (``Action``, ``ChatConfirmRequest``,
    ``ChatConfirmResponse``, ``ActionResult``) shared by ``/chat`` and
    ``/chat/confirm``, and
  - the read-only ``/coach`` namespace responses (progression, balance, recap,
    briefing) plus the ``PRBadge`` returned on a new personal record.

These are leaf models (pydantic only), so any feature — including ``app.chat`` —
can import them without an import cycle.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── PR celebration (Feature 3) ──
class PRBadge(BaseModel):
    is_pr: bool
    value: float          # the new best weight (kg)
    prev_best: float | None = None  # previous best, None if first-ever


# ── Propose → confirm (the human-in-the-loop contract) ──
class Action(BaseModel):
    """One model-proposed write, returned to the app for approval. The args use
    HUMAN references (exercise name, a date/"today", a workout title) — never raw
    IDs; those are resolved only at confirm time."""

    action_id: str
    type: str                      # the write tool name, e.g. "log_sets"
    summary: str                   # human-readable "what I'll do"
    args: dict[str, Any]
    status: str = "pending"
    needs_clarification: bool = False
    clarification: str | None = None


class ChatConfirmRequest(BaseModel):
    conversation_id: str
    accepted_ids: list[str] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)


class ActionResult(BaseModel):
    action_id: str
    # executed | failed | rejected | needs_clarification | not_found | already_executed
    status: str
    created_id: str | None = None
    detail: str | None = None
    pr: PRBadge | None = None  # set when an executed log_sets produced a new PR


class ChatConfirmResponse(BaseModel):
    reply: str
    results: list[ActionResult]


# ── /coach namespace (read-only, deterministic + cacheable) ──
class ProgressionItem(BaseModel):
    exercise_id: str
    exercise_name: str
    action: str                    # increase_weight | add_reps | hold | baseline
    current_weight: float | None
    suggested_weight: float | None
    target_reps: int | None
    reason: str


class ProgressionResponse(BaseModel):
    workout_id: str
    items: list[ProgressionItem]


class BalanceImbalance(BaseModel):
    type: str
    message: str
    suggest_muscles: list[str]


class BalanceResponse(BaseModel):
    push_sets: int
    pull_sets: int
    legs_sets: int
    push_pull_ratio: float | None
    imbalances: list[BalanceImbalance]
    balanced: bool


class RecapResponse(BaseModel):
    week: str                      # ISO week, e.g. "2026-W24"
    total_sessions: int
    total_sets: int
    prs: int
    streak: int
    best_lift: str | None
    text: str
    cached: bool = False


class BriefingResponse(BaseModel):
    date: datetime
    has_workout: bool
    title: str | None
    text: str
    cached: bool = False
