from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document import Document


class Chunk(Base):
    """A parsed, tokenised piece of a Document.

    embedding is nullable — it is NULL until the async embedding pipeline runs.
    The HNSW index on embedding is created in the Alembic migration; NULL rows
    are automatically excluded from the index.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised user_id for fast user-scoped retrieval queries
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 384-dim sentence-transformers/all-MiniLM-L6-v2 vector (default, free, local).
    # Change EMBEDDING_DIMENSIONS and run the matching Alembic migration to switch
    # to a different model (e.g., OpenAI text-embedding-3-small → 1536 dims).
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=True)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Arbitrary metadata (section heading, source URL, etc.)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ────────────────────────────────────────────────────────
    document: Mapped[Document] = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<Chunk id={self.id} doc_id={self.document_id} index={self.chunk_index}>"
        )
