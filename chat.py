from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta
import anthropic
from schema import ChatRequest
from security import get_current_user
from database import get_db
from config import settings

router = APIRouter()

# ─────────────────────────────────────────────────────────
#  POST /chat
#  Send a message to the AI coach.
#  The backend fetches the user's recent sessions,
#  builds a context summary, and sends everything to Claude.
#
#  Body: { message: str, history: [{role, content}] }
#  Response: { reply: str }
# ─────────────────────────────────────────────────────────
@router.post("")
async def chat(
    body: ChatRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    # ── 1. Fetch last 30 days of sessions with exercise names ──
    uid  = current_user["_id"]
    since = datetime.utcnow() - timedelta(days=30)

    sessions = await db["sessions"].find({
        "user_id": uid,
        "date":    {"$gte": since}
    }).sort("date", -1).limit(20).to_list(20)

    # Enrich sessions with exercise names
    session_summaries = []
    for s in sessions:
        ex = await db["exercises"].find_one({"_id": s["exercise_id"]})
        ex_name = ex["name"] if ex else "Unknown"
        muscle  = ex["muscle"] if ex else "unknown"
        sets_text = ", ".join(
            f"{st['weight_kg']}kg×{st['reps']}" for st in s["sets"]
        )
        session_summaries.append(
            f"- {s['date'].strftime('%d %b')}: {ex_name} ({muscle}) | {sets_text}"
        )

    # ── 2. Build system prompt with context ──
    context_block = "\n".join(session_summaries) if session_summaries else "No sessions logged yet."

    system_prompt = f"""You are IronLog AI, a knowledgeable and motivating personal fitness coach.
You have access to the user's real training data from the last 30 days shown below.
Use this data to give personalised, specific advice. Reference actual numbers from their sessions.
Be concise, practical, and encouraging. Never be generic — always tie your answer to their data.

USER: {current_user['name']}

RECENT TRAINING DATA (last 30 days):
{context_block}

Rules:
- Keep replies under 150 words unless a detailed explanation is truly needed.
- When recommending weight increases, suggest specific numbers based on their data.
- If they have no data yet, encourage them to log their first session.
- Never make up data — only use what is shown above.
"""

    # ── 3. Build message history for Claude ──
    messages = []
    for msg in body.history[-10:]:  # last 10 messages for context window efficiency
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": body.message})

    # ── 4. Call Claude API ──
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system=system_prompt,
        messages=messages,
    )

    reply = response.content[0].text
    return {"reply": reply}