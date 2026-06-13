"""AI coach orchestration.

Per turn this: resolves (or creates) the persistent conversation, assembles the
context — last-30-days training data + published references + rolling summary +
the recent raw turns — calls Gemini, saves both turns, and folds older turns into
the summary once the active window crosses the token threshold.

Persistence and the summarisation boundary maths live in ``app.conversations``;
the Gemini calls live in ``app.chat.gemini``. This module only wires them
together, so the data-access layer stays free of FastAPI and the LLM.

Security: every database read here is scoped to ``user["_id"]``, which comes
from the verified JWT (see ``app.auth.dependencies.get_current_user``) — never
from the request body. The model only ever sees the logged-in user's own data.
"""
import logging
from datetime import timedelta

from google.genai import types

from app.chat import gemini
from app.chat.schemas import ChatRequest
from app.coach import actions as coach_actions
from app.coach import agent
from app.coach.schemas import Action, ChatConfirmRequest, ChatConfirmResponse
from app.config import settings
from app.conversations import service as conversations
from app.conversations.models import ROLE_ASSISTANT, ROLE_USER
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.helpers.exceptions import AppError
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION
from app.workouts.models import COLLECTION as WORKOUTS_COLLECTION

logger = logging.getLogger(__name__)

CONTEXT_DAYS = 30


def _sets_text(sets: list[dict]) -> str:
    return ", ".join(f"{st['weight_kg']}kg×{st['reps']}" for st in sets)


async def _build_training_block(db, user: dict) -> str:
    """The user's last 30 days of training, organised by session (workout).

    Each session shows its date, title, the muscle groups worked, and the exercises
    logged under it. Scoped to ``user["_id"]`` so it can only read this user's own data.
    """
    user_id = user["_id"]
    since = now_utc() - timedelta(days=CONTEXT_DAYS)

    workouts = await db[WORKOUTS_COLLECTION].find(
        {"user_id": user_id, "date": {"$gte": since}}
    ).sort("date", -1).limit(40).to_list(40)

    lines: list[str] = []
    for w in workouts:
        groups = ", ".join(w.get("muscle_groups", [])) or "no muscle groups yet"
        lines.append(f"{w['date'].strftime('%d %b')} — {w['title']} [{groups}]")

        logs = await db[SESSIONS_COLLECTION].find(
            {"user_id": user_id, "workout_id": w["_id"]}
        ).sort("date", 1).to_list(100)
        for s in logs:
            # Re-assert ownership on the exercise lookup (defence in depth).
            ex = await db[EXERCISES_COLLECTION].find_one(
                {"_id": s["exercise_id"], "user_id": user_id}
            )
            ex_name = ex["name"] if ex else "Unknown"
            muscle = ex["muscle"] if ex else "unknown"
            line = f"  • {ex_name} ({muscle}): {_sets_text(s['sets'])}"
            note = (s.get("notes") or "").strip()
            if note:
                line += f"  — note: {note}"
            lines.append(line)
        if not logs:
            lines.append("  • (no sets logged yet)")

    return "\n".join(lines) if lines else "No sessions logged yet."


def _build_system_prompt(
    user_name: str, training_block: str, reference_block: str, summary: str | None
) -> str:
    """Coach persona + the live training data, plus two clearly separated,
    optional context blocks: curated published references, and the condensed
    summary of earlier turns in this conversation."""
    sections = [
        "You are IronLog's strength coach with LIVE access to the user's training app "
        "through tools. When the user asks you to log, plan, change, or schedule "
        "something, CALL the appropriate tool(s) instead of describing the steps by "
        "hand. Use the READ tools to ground every piece of advice in the user's real "
        "data first, then emit ALL needed WRITE tools together in one turn.",
        "Writes are NOT applied immediately: each becomes a proposal the user must "
        "approve in the app. When you propose actions, briefly state what you'll add "
        "or change and that the user must approve it.",
        "NEVER fabricate ids — refer to exercises by NAME and days by DATE (use 'today' "
        "or YYYY-MM-DD), and let the system resolve them. If a request is ambiguous, "
        "ask ONE short clarifying question instead of guessing.",
        "You also have the user's real training data from the last 30 days shown below. "
        "Use it to give personalised, specific advice and reference actual numbers.",
        "Be concise, practical, and encouraging. Never be generic — always tie your answer to their data.",
        "Each training day is a SESSION whose title tells you the day type (e.g. Push, Pull, "
        "Legs, Rest, Cardio, Full Body) — weigh your advice on recovery, balance, and what to "
        "train next around that. Each exercise line may end with the user's own note "
        "(how the set felt, pain, RPE, form cues) — read these notes and factor them into your "
        "feedback.",
        f"\nUSER: {user_name}",
        "\nTRAINING DATA FORMAT: each line `DD Mon — <Session title> [muscle groups]` is one "
        "session; indented `• exercise (muscle): sets — note: ...` lines are what was logged.",
        f"\nRECENT TRAINING DATA (last {CONTEXT_DAYS} days):\n{training_block}",
    ]

    if reference_block:
        sections.append(
            "\nPUBLISHED REFERENCE MATERIAL (curated by the user as authoritative "
            "background — not part of the live conversation):\n"
            f"{reference_block}"
        )

    if summary:
        sections.append(
            "\nCONVERSATION SUMMARY (earlier messages in this conversation, condensed):\n"
            f"{summary}"
        )

    sections.append(
        "\nRules:\n"
        "- Keep replies under 150 words unless a detailed explanation is truly needed.\n"
        "- When recommending weight increases, suggest specific numbers based on their data.\n"
        "- Use the session titles to reason about split balance and recovery (e.g. back-to-back "
        "push days, no rest/legs day), and quote the user's notes when they explain your advice.\n"
        "- If they have no data yet, encourage them to log their first session.\n"
        "- Never make up data — only use what is shown above."
    )
    return "\n".join(sections)


async def _maybe_summarize(db, conversation_id, user_id) -> None:
    """Fold older turns into the rolling summary once the active window exceeds
    the token threshold. Best-effort: a summarisation failure is logged but never
    breaks the chat reply (the raw messages are still safely stored)."""
    try:
        pending = await conversations.pending_summarization(
            db,
            conversation_id,
            user_id,
            settings.CHAT_SUMMARY_TOKEN_THRESHOLD,
            settings.CHAT_HISTORY_LIMIT,
        )
        if not pending:
            return
        _conv, overflow, boundary_seq, previous_summary = pending
        new_summary = await gemini.summarize(previous_summary, overflow)
        await conversations.apply_summary(
            db, conversation_id, user_id, new_summary, boundary_seq
        )
    except AppError as e:
        logger.warning("Summarisation skipped for %s: %s", conversation_id, e.detail)
    except Exception:  # never let memory maintenance break the user's reply
        logger.exception("Unexpected error summarising conversation %s", conversation_id)


async def chat(db, user: dict, body: ChatRequest) -> tuple[str, str, list[Action]]:
    """Run one agentic chat turn.

    Returns ``(reply, conversation_id, proposed_actions)``. Read tools auto-execute
    inside the agent loop; any write tools the model emits come back as
    ``proposed_actions`` (persisted as ``pending``) and are applied only after the
    user confirms them via :func:`confirm`.
    """
    if not settings.GEMINI_API_KEY:
        # 500: a configuration problem, not a client error.
        raise AppError("GEMINI_API_KEY not configured")

    user_id = user["_id"]

    # 1. Resolve or create the conversation — the server owns history now.
    if body.conversation_id:
        conversation = await conversations.require_conversation(
            db, user_id, body.conversation_id
        )
    else:
        conversation = await conversations.create_conversation(
            db, user_id, title=conversations.derive_title(body.message)
        )

    # 2. Assemble context: training data + published refs + summary + recent turns.
    training_block = await _build_training_block(db, user)
    reference_block = await conversations.build_reference_block(
        db, user_id, body.reference_labels, exclude_id=conversation["_id"]
    )
    recent = await conversations.load_recent_messages(db, conversation)
    system_prompt = _build_system_prompt(
        user["name"], training_block, reference_block, conversation.get("summary")
    )

    # Gemini uses the roles "user" and "model" (not "assistant").
    contents = []
    for m in recent:
        role = "model" if m["role"] == ROLE_ASSISTANT else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=body.message)]))

    # 3. Run the agentic loop (reads auto-exec; writes → proposals).
    reply, proposals, usage = await agent.run_turn(db, user_id, system_prompt, contents)

    # 4. Persist both turns. The assistant token count is the loop's summed output.
    await conversations.append_message(db, conversation, ROLE_USER, body.message)
    await conversations.append_message(
        db,
        conversation,
        ROLE_ASSISTANT,
        reply,
        token_count=usage.get("candidates_tokens") or None,
    )

    # 5. Persist pending proposals so /chat/confirm can find them by action_id.
    if proposals:
        await coach_actions.persist_proposals(
            db, conversation["_id"], user_id, proposals
        )

    # 6. Compress older turns if we crossed the token threshold.
    await _maybe_summarize(db, conversation["_id"], user_id)

    return reply, str(conversation["_id"]), proposals


async def confirm(db, user: dict, body: ChatConfirmRequest) -> ChatConfirmResponse:
    """Apply the actions the user accepted (and record any they rejected).

    Delegates to ``coach.actions.confirm``, which executes accepted actions
    transactionally, in a dependency-safe order, and idempotently (re-confirming
    never double-writes). Templated reply by default — no Gemini call unless
    ``COACH_CONFIRM_USE_LLM`` is enabled."""
    return await coach_actions.confirm(
        db, user, body.conversation_id, body.accepted_ids, body.rejected_ids
    )
