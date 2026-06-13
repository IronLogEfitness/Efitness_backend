"""The agentic loop for one chat turn.

Drives Gemini with the tool registry under the human-in-the-loop rule:
  - READ calls auto-execute (they only fetch the user's own data) and their results
    are fed back so the model can ground its reasoning.
  - WRITE calls are NEVER executed here — each becomes a pending ``Action`` proposal
    and the loop stops, handing control to the user via ``/chat/confirm``.

The loop is hard-capped at ``COACH_MAX_TOOL_ITERATIONS`` to protect the free-tier
request quota, and logs per-turn token/request usage.
"""
import logging
import uuid

from google.genai import types
from pydantic import ValidationError

from app.chat import gemini
from app.coach import tools
from app.coach.schemas import Action
from app.config import settings
from app.helpers.exceptions import AppError

logger = logging.getLogger(__name__)


def _extract(response) -> tuple[str, list, object]:
    """Pull ``(text, function_calls, model_content)`` off a Gemini response,
    tolerant of a missing candidate / parts."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "", [], None
    content = candidates[0].content
    text_parts: list[str] = []
    calls: list = []
    for part in (getattr(content, "parts", None) or []):
        if getattr(part, "function_call", None):
            calls.append(part.function_call)
        elif getattr(part, "text", None):
            text_parts.append(part.text)
    return "\n".join(text_parts).strip(), calls, content


def _wrap(result) -> dict:
    """Function responses must be JSON objects; wrap a non-dict result."""
    return result if isinstance(result, dict) else {"result": result}


def _validation_message(name: str, err: Exception) -> str:
    """Turn a Pydantic error into one short, user-facing clarification."""
    if isinstance(err, ValidationError) and err.errors():
        first = err.errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ())) or "input"
        return f"I need a valid '{field}' to {name.replace('_', ' ')}."
    return f"I need a bit more detail to {name.replace('_', ' ')}."


def _to_action(call) -> Action:
    """Validate one write call into a proposal (or a needs_clarification stub)."""
    raw = dict(call.args or {})
    action_id = uuid.uuid4().hex
    try:
        clean_args, summary = tools.validate_write(call.name, raw)
        return Action(
            action_id=action_id, type=call.name, summary=summary, args=clean_args
        )
    except (ValidationError, ValueError, KeyError) as e:
        return Action(
            action_id=action_id,
            type=call.name,
            summary=f"(needs more info for {call.name})",
            args=raw,
            status="needs_clarification",
            needs_clarification=True,
            clarification=_validation_message(call.name, e),
        )


def _fallback_reply(proposals: list[Action]) -> str:
    """A templated reply when the model proposed writes but returned no text."""
    actionable = [p for p in proposals if not p.needs_clarification]
    if not actionable:
        questions = [p.clarification for p in proposals if p.clarification]
        return questions[0] if questions else "I need a little more detail to do that."
    lines = "; ".join(p.summary for p in actionable)
    return f"Here's what I'll do — approve to apply: {lines}"


async def run_turn(
    db, user_id, system_instruction: str, contents: list
) -> tuple[str, list[Action], dict]:
    """Run the loop. ``contents`` is a mutable list of ``types.Content`` (history +
    the current user message). Returns ``(reply_text, proposals, usage_totals)``."""
    usage = {"requests": 0, "prompt_tokens": 0, "candidates_tokens": 0}

    for iteration in range(settings.COACH_MAX_TOOL_ITERATIONS):
        response = await gemini.generate_with_tools(
            system_instruction, contents, tools.DECLARATIONS
        )
        usage["requests"] += 1
        meta = gemini._usage_from(response)
        usage["prompt_tokens"] += meta.get("prompt_token_count") or 0
        usage["candidates_tokens"] += meta.get("candidates_token_count") or 0

        text, calls, model_content = _extract(response)

        # No tool calls → this is the final natural-language answer.
        if not calls:
            logger.info("coach turn complete (%d iter, usage=%s)", iteration + 1, usage)
            return (text or "Done.", [], usage)

        # Keep the model's call turn in the transcript we send back.
        if model_content is not None:
            contents.append(model_content)

        write_calls = [c for c in calls if c.name in tools.WRITE_TOOL_NAMES]
        if write_calls:
            # Human-in-the-loop: collect proposals and stop. We do NOT also run any
            # read calls in this turn — the model has decided to act.
            proposals = [_to_action(c) for c in write_calls]
            reply = text or _fallback_reply(proposals)
            logger.info(
                "coach proposed %d action(s) (%d iter, usage=%s)",
                len(proposals), iteration + 1, usage,
            )
            return (reply, proposals, usage)

        # Only read calls: execute each and feed the results back.
        parts: list[types.Part] = []
        for c in calls:
            name = c.name
            if name in tools.READ_TOOL_NAMES:
                try:
                    result = await tools.execute_read(db, user_id, name, dict(c.args or {}))
                except AppError as e:
                    result = {"error": e.detail}
                except Exception:  # never let a tool crash the turn
                    logger.exception("read tool %s failed", name)
                    result = {"error": f"{name} failed unexpectedly"}
            else:
                result = {"error": f"unknown tool {name}"}
            parts.append(types.Part.from_function_response(name=name, response=_wrap(result)))
        contents.append(types.Content(role="user", parts=parts))

    logger.warning("coach loop hit the %d-iteration cap", settings.COACH_MAX_TOOL_ITERATIONS)
    return (
        "I pulled up your data but ran out of steps before finishing — "
        "could you rephrase what you'd like me to do?",
        [],
        usage,
    )
