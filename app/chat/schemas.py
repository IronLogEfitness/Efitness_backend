"""Request / response models for the AI chat endpoint."""
from pydantic import BaseModel

from app.coach.schemas import Action


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    # Continue an existing thread. Omit to start a new conversation; the id is
    # returned in the response so the client can pass it back next turn.
    conversation_id: str | None = None
    # Optional: inject the user's own published reference conversations whose
    # `label` matches one of these (see app.conversations Feature 3).
    reference_labels: list[str] | None = None
    # Deprecated: history is now owned by the server and IGNORED. Kept so older
    # clients don't break; will be removed in a future release.
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    # Writes the coach wants to make, awaiting the user's approval via /chat/confirm.
    # Empty for a plain Q&A turn (backward compatible with older clients).
    proposed_actions: list[Action] = []
