"""AI chat endpoint: POST /chat."""
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.chat import service
from app.chat.schemas import ChatRequest, ChatResponse
from app.core.database import get_db

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    reply, conversation_id = await service.chat(db, current_user, body)
    return ChatResponse(reply=reply, conversation_id=conversation_id)
