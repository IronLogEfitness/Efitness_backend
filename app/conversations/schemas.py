"""Request / response models for the conversation endpoints."""
from datetime import datetime

from pydantic import BaseModel, model_validator


# ── Import ──
class ImportMessage(BaseModel):
    role: str  # "user" | "assistant" | "model" (Gemini's name) — normalised in the service
    content: str


class ConversationImportRequest(BaseModel):
    """Import a Gemini conversation. Provide *exactly one* of:

    - ``messages``: an already-segmented list of turns, or
    - ``raw_text``: the conversation copy-pasted as text (parsed server-side).
    """

    title: str | None = None
    messages: list[ImportMessage] | None = None
    raw_text: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "ConversationImportRequest":
        if bool(self.messages) == bool(self.raw_text):
            raise ValueError("Provide exactly one of `messages` or `raw_text`.")
        return self


# ── Update (publish / label / rename) ──
class ConversationUpdate(BaseModel):
    title: str | None = None
    is_published: bool | None = None
    label: str | None = None


# ── Responses ──
class ConversationResponse(BaseModel):
    id: str
    title: str | None
    source: str
    is_published: bool
    label: str | None
    message_count: int
    has_summary: bool
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    id: str
    seq: int
    role: str
    content: str
    token_count: int
    created_at: datetime


class ConversationDetailResponse(ConversationResponse):
    summary: str | None
    messages: list[MessageResponse]
