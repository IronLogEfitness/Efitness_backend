"""Thin async wrapper around the Google Gemini client.

Centralises the model choice, per-request client creation (so a blank API key
never crashes startup), generation config, and error handling, so both the live
chat reply and the conversation-summarisation call share one implementation.
Every failure surfaces as an ``AppError`` (mapped to JSON by the app handler).

This module is a leaf: it imports only config + the error type, so any feature
can depend on it without creating an import cycle.
"""
import asyncio
import logging

from google import genai
from google.genai import types

from app.config import settings
from app.helpers.exceptions import AppError

logger = logging.getLogger(__name__)

CHAT_MODEL = "gemini-2.5-flash"
MAX_OUTPUT_TOKENS = 800
SUMMARY_MAX_OUTPUT_TOKENS = 400
# Tool turns can carry several parallel function calls plus a sentence of text,
# so give them a little more room than a plain reply.
TOOLS_MAX_OUTPUT_TOKENS = 1200
COMPOSE_MAX_OUTPUT_TOKENS = 400

# Transient upstream failures (model overloaded, rate limited, timeouts) are worth
# retrying with a short exponential backoff instead of failing the user's turn.
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0  # seconds: waits ~1s, ~2s between attempts
_TRANSIENT_MARKERS = (
    "503", "unavailable", "overloaded", "high demand",
    "429", "resource_exhausted", "rate limit",
    "500", "internal", "timeout", "deadline",
)
# Shown to the user when even the retries can't get through — no raw API dump.
_BUSY_MESSAGE = (
    "The AI coach is busy right now (high demand on the model). "
    "Please try again in a few seconds."
)


def _client() -> genai.Client:
    # Created per call (not at import) so a blank key never crashes startup.
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _is_transient(error: Exception) -> bool:
    msg = str(error).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


async def _generate(model: str, contents: list, config: "types.GenerateContentConfig"):
    """Call Gemini with retries on transient (overload/rate-limit) failures."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return await _client().aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as e:  # noqa: BLE001 — classify, then retry or re-raise
            last_error = e
            if _is_transient(e) and attempt < MAX_ATTEMPTS - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Gemini transient error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, MAX_ATTEMPTS, delay, e,
                )
                await asyncio.sleep(delay)
                continue
            raise
    assert last_error is not None
    raise last_error


# Turn off "thinking" so the whole token budget goes to the output. Gemini 2.5
# Flash otherwise spends tokens on hidden reasoning and can return an empty
# message under a small max_output_tokens.
_NO_THINKING = types.ThinkingConfig(thinking_budget=0)


def _usage_from(response) -> dict:
    """Pull Gemini's token accounting off a response (so callers can log/store
    exact counts for free). Returns an empty dict when metadata is absent."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    return {
        "prompt_token_count": getattr(meta, "prompt_token_count", None),
        "candidates_token_count": getattr(meta, "candidates_token_count", None),
    }


async def generate(system_instruction: str, contents: list) -> tuple[str, dict]:
    """Run one chat turn. Returns ``(reply_text, usage)`` where ``usage`` holds
    Gemini's token accounting (so the caller can store exact counts for free).
    Raises ``AppError`` on an upstream failure or empty reply."""
    try:
        response = await _generate(
            CHAT_MODEL,
            contents,
            types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=_NO_THINKING,
            ),
        )
    except Exception as e:  # surface upstream AI errors as a clean response
        if _is_transient(e):
            raise AppError(_BUSY_MESSAGE)
        raise AppError(f"AI request failed: {e}")

    reply = response.text
    if not reply:
        raise AppError("The AI returned an empty response. Please try again.")

    return reply, _usage_from(response)


async def generate_with_tools(
    system_instruction: str,
    contents: list,
    declarations: "list[types.FunctionDeclaration]",
) -> object:
    """Run one tool-enabled turn for the agent loop. Returns the *raw* Gemini
    response so the caller can inspect both ``function_calls`` and any text.

    ``automatic_function_calling`` is DISABLED: the SDK must never run a tool on
    its own. Every write tool is collected as a proposal and only executed after
    the user confirms (see ``app.coach.agent`` / ``app.coach.actions``)."""
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=TOOLS_MAX_OUTPUT_TOKENS,
        thinking_config=_NO_THINKING,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    try:
        return await _generate(CHAT_MODEL, contents, config)
    except Exception as e:
        if _is_transient(e):
            raise AppError(_BUSY_MESSAGE)
        raise AppError(f"AI request failed: {e}")


async def compose(
    system_instruction: str,
    prompt: str,
    max_output_tokens: int = COMPOSE_MAX_OUTPUT_TOKENS,
) -> tuple[str, dict]:
    """One-shot text generation for optional phrasing (confirmation sentence,
    weekly recap, briefing). Returns ``(text, usage)``. Raises ``AppError`` on an
    upstream failure; callers treat phrasing as best-effort and fall back to a
    template."""
    try:
        response = await _generate(
            CHAT_MODEL,
            [{"role": "user", "parts": [{"text": prompt}]}],
            types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=max_output_tokens,
                thinking_config=_NO_THINKING,
            ),
        )
    except Exception as e:
        if _is_transient(e):
            raise AppError(_BUSY_MESSAGE)
        raise AppError(f"AI request failed: {e}")

    text = response.text
    if not text:
        raise AppError("The AI returned an empty response.")
    return text.strip(), _usage_from(response)


async def summarize(previous_summary: str | None, messages: list[dict]) -> str:
    """Condense earlier turns (plus any existing summary) into a compact running
    memory. Used by the sliding-window summarisation. Raises ``AppError`` on an
    upstream failure; the caller treats summarisation as best-effort."""
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)

    prompt_parts = []
    if previous_summary:
        prompt_parts.append(f"Summary so far:\n{previous_summary}\n")
    prompt_parts.append(
        "Update the running summary by folding in the conversation turns below. "
        "Preserve concrete facts, goals, numbers, preferences and commitments. "
        "Write 3-6 tight sentences, no preamble.\n\n"
        f"{transcript}"
    )

    try:
        response = await _generate(
            CHAT_MODEL,
            [{"role": "user", "parts": [{"text": "\n".join(prompt_parts)}]}],
            types.GenerateContentConfig(
                system_instruction=(
                    "You compress fitness-coaching conversations into a compact running memory."
                ),
                max_output_tokens=SUMMARY_MAX_OUTPUT_TOKENS,
                thinking_config=_NO_THINKING,
            ),
        )
    except Exception as e:
        raise AppError(f"AI summarisation failed: {e}")

    summary = response.text
    if not summary:
        # Don't lose memory entirely if the model returns nothing.
        return previous_summary or transcript
    return summary.strip()
