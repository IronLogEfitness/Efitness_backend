"""Request / response models for the AI chat endpoint."""
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []  # full conversation so far


class ChatResponse(BaseModel):
    reply: str
