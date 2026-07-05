"""Pydantic schemas shared across the RAG pipeline.

These are *service-layer* schemas — they travel between RetrievalService,
PromptService, and GenerationService.  Part 7 will expose them as API
response models via thin wrappers in the router layer.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class RetrievalResult(BaseModel):
    """A single ranked chunk returned by the retrieval layer."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    content: str
    score: float = Field(ge=0.0, le=1.0, description="Cosine similarity (0–1)")
    chunk_index: int
    page_number: int | None = None
    source_filename: str
    chunk_metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class ChatTurn(BaseModel):
    """A single turn in a conversation (user or assistant message)."""

    role: str  # "user" | "assistant" | "system"
    content: str

    model_config = {"frozen": True}


class Citation(BaseModel):
    """A source reference extracted from the generated answer."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: int | None = None
    snippet: str = Field(description="First 200 chars of the cited chunk")
    source_filename: str
    score: float = Field(description="Retrieval relevance score")

    model_config = {"frozen": True}


class GenerationResult(BaseModel):
    """Complete result from the generation pipeline."""

    answer: str
    citations: list[Citation]
    model: str
    prompt_tokens: int
    completion_tokens: int

    model_config = {"frozen": True}
