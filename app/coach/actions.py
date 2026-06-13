"""Proposal persistence + the confirm step (execute accepted actions).

``persist_proposals`` writes pending proposals so ``/chat/confirm`` can find them
by ``action_id``. ``confirm`` then:
  - marks ``rejected_ids`` rejected,
  - executes ``accepted_ids`` in a dependency-safe order (creates before the rows
    that reference them), each guarded by an **atomic** pending→executing claim so a
    re-submitted confirm never double-writes (idempotency),
  - records what happened as an assistant message (so the model is aware next turn),
  - and returns one reply (templated by default; one Gemini call only when
    ``COACH_CONFIRM_USE_LLM`` is on).
"""
import logging

from app.chat import gemini
from app.coach import execute
from app.coach.models import (
    COACH_ACTIONS_COLLECTION,
    STATUS_EXECUTED,
    STATUS_EXECUTING,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REJECTED,
    CoachActionDocument,
)
from app.coach.resolve import NeedsClarification
from app.coach.schemas import Action, ActionResult, ChatConfirmResponse, PRBadge
from app.config import settings
from app.conversations import service as conversations
from app.conversations.models import ROLE_ASSISTANT
from app.helpers.dates import now_utc
from app.helpers.exceptions import AppError

logger = logging.getLogger(__name__)


async def persist_proposals(
    db, conversation_id, user_id, proposals: list[Action]
) -> None:
    """Store the well-formed pending proposals. ``needs_clarification`` proposals are
    returned to the app but not persisted — they can't be executed, and the model
    should re-propose them cleanly next turn."""
    docs = [
        CoachActionDocument(
            conversation_id=conversation_id,
            user_id=user_id,
            action_id=a.action_id,
            type=a.type,
            args=a.args,
            summary=a.summary,
        ).model_dump()
        for a in proposals
        if not a.needs_clarification
    ]
    if docs:
        await db[COACH_ACTIONS_COLLECTION].insert_many(docs)


async def _reject(db, cid, user_id, action_id: str) -> ActionResult:
    doc = await db[COACH_ACTIONS_COLLECTION].find_one_and_update(
        {
            "conversation_id": cid,
            "user_id": user_id,
            "action_id": action_id,
            "status": STATUS_PENDING,
        },
        {"$set": {"status": STATUS_REJECTED, "updated_at": now_utc()}},
    )
    if doc is not None:
        return ActionResult(action_id=action_id, status=STATUS_REJECTED)
    existing = await db[COACH_ACTIONS_COLLECTION].find_one(
        {"conversation_id": cid, "user_id": user_id, "action_id": action_id}
    )
    if existing is None:
        return ActionResult(action_id=action_id, status="not_found")
    return ActionResult(action_id=action_id, status=existing["status"])  # already settled


async def _set_status(db, _id, status: str, detail: str | None = None) -> None:
    await db[COACH_ACTIONS_COLLECTION].update_one(
        {"_id": _id}, {"$set": {"status": status, "detail": detail, "updated_at": now_utc()}}
    )


async def _execute_one(db, user_id, doc) -> ActionResult:
    aid = doc["action_id"]

    # Atomically claim: only a still-PENDING action transitions to EXECUTING. This is
    # the idempotency guard — a concurrent / repeated confirm won't re-run it.
    claimed = await db[COACH_ACTIONS_COLLECTION].find_one_and_update(
        {"_id": doc["_id"], "status": STATUS_PENDING},
        {"$set": {"status": STATUS_EXECUTING, "updated_at": now_utc()}},
    )
    if claimed is None:
        current = await db[COACH_ACTIONS_COLLECTION].find_one({"_id": doc["_id"]})
        if current and current["status"] == STATUS_EXECUTED:
            return ActionResult(
                action_id=aid,
                status="already_executed",
                created_id=current.get("created_id"),
                detail=current.get("detail"),
            )
        return ActionResult(
            action_id=aid,
            status=current["status"] if current else "not_found",
            detail=(current or {}).get("detail"),
        )

    try:
        res = await execute.execute_action(db, user_id, doc["type"], doc["args"])
    except NeedsClarification as e:
        # Revert to pending so the user can answer and retry the same action.
        await _set_status(db, doc["_id"], STATUS_PENDING, detail=e.message)
        return ActionResult(action_id=aid, status="needs_clarification", detail=e.message)
    except AppError as e:
        await _set_status(db, doc["_id"], STATUS_FAILED, detail=e.detail)
        return ActionResult(action_id=aid, status=STATUS_FAILED, detail=e.detail)
    except Exception:
        logger.exception("Unexpected error executing action %s", aid)
        await _set_status(db, doc["_id"], STATUS_FAILED, detail="Internal error")
        return ActionResult(action_id=aid, status=STATUS_FAILED, detail="Internal error")

    await db[COACH_ACTIONS_COLLECTION].update_one(
        {"_id": doc["_id"]},
        {"$set": {
            "status": STATUS_EXECUTED,
            "created_id": res.created_id,
            "detail": res.detail,
            "updated_at": now_utc(),
        }},
    )
    return ActionResult(
        action_id=aid,
        status=STATUS_EXECUTED,
        created_id=res.created_id,
        detail=res.detail,
        pr=PRBadge(**res.pr) if res.pr else None,
    )


def _template_reply(results: list[ActionResult]) -> str:
    done = [r for r in results if r.status == STATUS_EXECUTED]
    already = [r for r in results if r.status == "already_executed"]
    clarify = [r for r in results if r.status == "needs_clarification"]
    failed = [r for r in results if r.status == STATUS_FAILED]
    rejected = [r for r in results if r.status == STATUS_REJECTED]

    parts: list[str] = []
    applied = done + already
    if applied:
        parts.append("✅ " + " ".join(r.detail for r in applied if r.detail))
    pr_hits = [r for r in done if r.pr]
    for r in pr_hits:
        parts.append(f"🏆 New PR: {r.pr.value:g}kg!")
    if clarify:
        parts.append(" ".join(r.detail for r in clarify if r.detail))
    if failed:
        parts.append("⚠️ Couldn't apply: " + "; ".join(r.detail or "error" for r in failed))
    if rejected:
        parts.append(f"Skipped {len(rejected)}.")
    return " ".join(p for p in parts if p.strip()) or "Nothing to apply."


async def _confirmation_reply(results: list[ActionResult]) -> str:
    template = _template_reply(results)
    if not settings.COACH_CONFIRM_USE_LLM:
        return template
    try:
        text, _ = await gemini.compose(
            "You are IronLog's coach. In one short, motivating sentence, confirm what "
            "was just logged or changed. Keep it specific and under 30 words.",
            f"Actions just applied: {template}",
        )
        return text
    except AppError:
        return template  # phrasing is best-effort


async def confirm(
    db, user, conversation_id: str, accepted_ids: list[str], rejected_ids: list[str]
) -> ChatConfirmResponse:
    """Execute accepted actions transactionally and idempotently; record rejects."""
    user_id = user["_id"]
    conversation = await conversations.require_conversation(db, user_id, conversation_id)
    cid = conversation["_id"]

    results: list[ActionResult] = []

    for aid in dict.fromkeys(rejected_ids or []):  # de-dupe, preserve order
        results.append(await _reject(db, cid, user_id, aid))

    # Load accepted actions and order them so dependencies execute first.
    accepted_docs = []
    for aid in dict.fromkeys(accepted_ids or []):
        doc = await db[COACH_ACTIONS_COLLECTION].find_one(
            {"conversation_id": cid, "user_id": user_id, "action_id": aid}
        )
        if doc is None:
            results.append(ActionResult(action_id=aid, status="not_found"))
        else:
            accepted_docs.append(doc)
    accepted_docs.sort(key=lambda d: execute.EXECUTION_ORDER.get(d["type"], 99))

    for doc in accepted_docs:
        results.append(await _execute_one(db, user_id, doc))

    reply = await _confirmation_reply(results)

    # Record the outcome so the model is aware of it on the next turn.
    await conversations.append_message(db, conversation, ROLE_ASSISTANT, reply)

    return ChatConfirmResponse(reply=reply, results=results)
