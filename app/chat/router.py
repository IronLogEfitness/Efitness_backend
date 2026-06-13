"""AI chat endpoints: POST /chat (agentic turn) and POST /chat/confirm (apply)."""
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.chat import service
from app.chat.schemas import ChatRequest, ChatResponse
from app.coach.schemas import ChatConfirmRequest, ChatConfirmResponse
from app.core.database import get_db

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    reply, conversation_id, proposed_actions = await service.chat(db, current_user, body)
    return ChatResponse(
        reply=reply,
        conversation_id=conversation_id,
        proposed_actions=proposed_actions,
    )


@router.post("/confirm", response_model=ChatConfirmResponse)
async def confirm(
    body: ChatConfirmRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Execute the proposed actions the user accepted (and record rejections).
    Idempotent: re-submitting the same accepted_ids never double-writes."""
    return await service.confirm(db, current_user, body)
