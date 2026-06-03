"""AI coach: builds a context summary from the user's recent training data and
sends it to Google Gemini.

Security: every database read here is scoped to ``user["_id"]``, which comes
from the verified JWT (see ``app.auth.dependencies.get_current_user``) — never
from the request body. The model therefore only ever sees the logged-in user's
own data, and nothing the user types in their message can change *whose* data is
fetched.
"""
from datetime import timedelta

from google import genai
from google.genai import types

from app.chat.schemas import ChatRequest
from app.config import settings
from app.exercises.models import COLLECTION as EXERCISES_COLLECTION
from app.helpers.dates import now_utc
from app.helpers.exceptions import AppError
from app.sessions.models import COLLECTION as SESSIONS_COLLECTION

CHAT_MODEL = "gemini-2.5-flash"
MAX_OUTPUT_TOKENS = 800
CONTEXT_DAYS = 30
HISTORY_LIMIT = 10  # last N messages kept for context-window efficiency


async def _build_context_block(db, user: dict) -> str:
    """A bullet list of the user's last 30 days of sessions, with exercise names.

    Scoped to ``user["_id"]`` so it can only read this user's own data.
    """
    user_id = user["_id"]
    since = now_utc() - timedelta(days=CONTEXT_DAYS)

    sessions = await db[SESSIONS_COLLECTION].find(
        {"user_id": user_id, "date": {"$gte": since}}
    ).sort("date", -1).limit(20).to_list(20)

    summaries = []
    for s in sessions:
        # Re-assert ownership on the exercise lookup (defence in depth).
        ex = await db[EXERCISES_COLLECTION].find_one(
            {"_id": s["exercise_id"], "user_id": user_id}
        )
        ex_name = ex["name"] if ex else "Unknown"
        muscle = ex["muscle"] if ex else "unknown"
        sets_text = ", ".join(
            f"{st['weight_kg']}kg×{st['reps']}" for st in s["sets"]
        )
        summaries.append(
            f"- {s['date'].strftime('%d %b')}: {ex_name} ({muscle}) | {sets_text}"
        )

    return "\n".join(summaries) if summaries else "No sessions logged yet."


def _build_system_prompt(user_name: str, context_block: str) -> str:
    return f"""You are IronLog AI, a knowledgeable and motivating personal fitness coach.
You have access to the user's real training data from the last 30 days shown below.
Use this data to give personalised, specific advice. Reference actual numbers from their sessions.
Be concise, practical, and encouraging. Never be generic — always tie your answer to their data.

USER: {user_name}

RECENT TRAINING DATA (last 30 days):
{context_block}

Rules:
- Keep replies under 150 words unless a detailed explanation is truly needed.
- When recommending weight increases, suggest specific numbers based on their data.
- If they have no data yet, encourage them to log their first session.
- Never make up data — only use what is shown above.
"""


async def chat(db, user: dict, body: ChatRequest) -> str:
    if not settings.GEMINI_API_KEY:
        # 500: a configuration problem, not a client error.
        raise AppError("GEMINI_API_KEY not configured")

    context_block = await _build_context_block(db, user)
    system_prompt = _build_system_prompt(user["name"], context_block)

    # Gemini uses the roles "user" and "model" (not "assistant").
    contents = []
    for msg in body.history[-HISTORY_LIMIT:]:
        role = "model" if msg.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg.content}]})
    contents.append({"role": "user", "parts": [{"text": body.message}]})

    # Created per-request (not at import) so a blank key never crashes startup.
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    try:
        response = await client.aio.models.generate_content(
            model=CHAT_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                # Turn off "thinking" so the whole token budget goes to the reply.
                # Gemini 2.5 Flash otherwise spends tokens on hidden reasoning and
                # can return an empty message under a small max_output_tokens.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except Exception as e:  # surface upstream AI errors as a clean response
        raise AppError(f"AI request failed: {e}")

    reply = response.text
    if not reply:
        raise AppError("The AI returned an empty response. Please try again.")
    return reply
