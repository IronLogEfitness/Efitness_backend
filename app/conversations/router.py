"""Conversation endpoints: import, list, detail, and publish/label updates,
all under /conversations and authenticated like the rest of the API."""
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.conversations import service
from app.conversations.schemas import (
    ConversationDetailResponse,
    ConversationImportRequest,
    ConversationResponse,
    ConversationUpdate,
)
from app.core.database import get_db
from app.helpers.filters import Pagination, pagination_params

router = APIRouter()


# Declared before "/{conversation_id}" so the literal path wins.
@router.post("/import", response_model=ConversationResponse, status_code=201)
async def import_conversation(
    body: ConversationImportRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.import_conversation(db, current_user["_id"], body)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    source: str | None = None,
    is_published: bool | None = None,
    page: Pagination = Depends(pagination_params),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.list_conversations(
        db, current_user["_id"], page, source, is_published
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    page: Pagination = Depends(pagination_params),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.get_conversation_detail(
        db, current_user["_id"], conversation_id, page
    )


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await service.update_conversation(
        db, current_user["_id"], conversation_id, body
    )
