import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.chat import MessageRole
from app.schemas.rag import Citation


class ChatMessageCreate(BaseModel):
    """Only the user's message content; role is always USER on creation."""

    content: str


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    role: MessageRole
    content: str
    sources: Any | None = None
    token_count: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatSessionUpdate(BaseModel):
    title: str | None = None


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageResponse] = []

    model_config = {"from_attributes": True}


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionResponse]
    total: int
    page: int
    size: int
    pages: int


# ── Chat query request / SSE event schemas ────────────────────────────────────


class ChatQueryRequest(BaseModel):
    """POST /chat/query request body."""

    message: str = Field(min_length=1, max_length=10_000)
    session_id: uuid.UUID | None = None


class ChatTokenEvent(BaseModel):
    """SSE event: a single streaming token from the LLM."""

    type: Literal["token"] = "token"
    content: str


class ChatDoneEvent(BaseModel):
    """SSE event: generation complete — sent as the last event."""

    type: Literal["done"] = "done"
    session_id: uuid.UUID
    message_id: uuid.UUID
    citations: list[Citation]
    model: str
    prompt_tokens: int
    completion_tokens: int


class ChatErrorEvent(BaseModel):
    """SSE event: terminal error during streaming."""

    type: Literal["error"] = "error"
    message: str
