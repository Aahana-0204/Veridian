import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ChunkBase(BaseModel):
    content: str
    chunk_index: int
    page_number: int | None = None
    token_count: int | None = None
    chunk_metadata: dict[str, Any] | None = None


class ChunkCreate(ChunkBase):
    document_id: uuid.UUID
    user_id: uuid.UUID


class ChunkResponse(ChunkBase):
    id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    # embedding intentionally omitted — it's a 1536-float vector (large payload)

    model_config = {"from_attributes": True}


class ChunkWithScore(ChunkResponse):
    """Chunk returned by semantic search, augmented with cosine similarity score."""

    score: float
    document_title: str | None = None
    document_filename: str | None = None
