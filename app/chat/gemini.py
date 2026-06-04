"""Thin async wrapper around the Google Gemini client.

Centralises the model choice, per-request client creation (so a blank API key
never crashes startup), generation config, and error handling, so both the live
chat reply and the conversation-summarisation call share one implementation.
Every failure surfaces as an ``AppError`` (mapped to JSON by the app handler).

This module is a leaf: it imports only config + the error type, so any feature
can depend on it without creating an import cycle.
"""
from google import genai
from google.genai import types

from app.config import settings
from app.helpers.exceptions import AppError

CHAT_MODEL = "gemini-2.5-flash"
MAX_OUTPUT_TOKENS = 800
SUMMARY_MAX_OUTPUT_TOKENS = 400


def _client() -> genai.Client:
    # Created per call (not at import) so a blank key never crashes startup.
    return genai.Client(api_key=settings.GEMINI_API_KEY)


# Turn off "thinking" so the whole token budget goes to the output. Gemini 2.5
# Flash otherwise spends tokens on hidden reasoning and can return an empty
# message under a small max_output_tokens.
_NO_THINKING = types.ThinkingConfig(thinking_budget=0)


async def generate(system_instruction: str, contents: list) -> tuple[str, dict]:
    """Run one chat turn. Returns ``(reply_text, usage)`` where ``usage`` holds
    Gemini's token accounting (so the caller can store exact counts for free).
    Raises ``AppError`` on an upstream failure or empty reply."""
    try:
        response = await _client().aio.models.generate_content(
            model=CHAT_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=_NO_THINKING,
            ),
        )
    except Exception as e:  # surface upstream AI errors as a clean response
        raise AppError(f"AI request failed: {e}")

    reply = response.text
    if not reply:
        raise AppError("The AI returned an empty response. Please try again.")

    usage: dict = {}
    meta = getattr(response, "usage_metadata", None)
    if meta is not None:
        usage = {
            "prompt_token_count": getattr(meta, "prompt_token_count", None),
            "candidates_token_count": getattr(meta, "candidates_token_count", None),
        }
    return reply, usage


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
        response = await _client().aio.models.generate_content(
            model=CHAT_MODEL,
            contents=[{"role": "user", "parts": [{"text": "\n".join(prompt_parts)}]}],
            config=types.GenerateContentConfig(
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
