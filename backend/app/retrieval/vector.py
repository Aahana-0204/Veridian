"""Vector similarity retriever using pgvector cosine distance.

Uses the ``<=>`` cosine-distance operator from pgvector to find the
nearest neighbours of the query embedding in the ``chunks`` table.

Key guarantees
--------------
- Results are **always** scoped to ``user_id`` (WHERE clause).
- Only chunks with non-null embeddings are considered.
- Score is ``1 − cosine_distance`` ∈ [0, 1] (higher = more similar).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.retrieval.base import AbstractRetriever
from app.schemas.rag import RetrievalResult

logger = structlog.get_logger(__name__)


class VectorRetriever(AbstractRetriever):
    """Retrieves chunks via pgvector ANN (approximate nearest-neighbour) search.

    The query text is first embedded using the configured ``EmbeddingProvider``,
    then the embedding is compared against stored chunk vectors via the
    pgvector ``<=>`` (cosine distance) operator.

    Parameters
    ----------
    embedding_provider:
        Any ``EmbeddingProvider`` instance — used to embed the query text.
    """

    def __init__(self, embedding_provider: object) -> None:
        # Keep import-free from EmbeddingProvider to avoid circular deps;
        # type is validated at runtime via duck-typing.
        self._embedding_provider = embedding_provider

    async def retrieve(
        self,
        query: str,
        user_id: uuid.UUID,
        session: AsyncSession,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Embed *query* and return the *top_k* most similar chunks for *user_id*."""
        # 1. Embed the query
        query_vectors: list[list[float]] = await self._embedding_provider.embed_batch(
            [query]
        )
        query_vec: list[float] = query_vectors[0]

        # 2. Build the distance expression using pgvector's <=> operator
        #    pgvector accepts a Python list[float] directly for the right-hand side.
        distance_expr = Chunk.embedding.op("<=>")(query_vec)
        score_expr = (1.0 - Chunk.embedding.op("<=>")(query_vec)).label("score")

        stmt = (
            select(Chunk, score_expr)
            .where(
                Chunk.user_id == user_id,
                Chunk.embedding.is_not(None),
            )
            .order_by(distance_expr)
            .limit(top_k)
        )

        rows = (await session.execute(stmt)).all()

        results: list[RetrievalResult] = []
        for row in rows:
            chunk: Chunk = row[0]
            raw_score: float = float(row[1])
            # Clamp to [0, 1] — floating-point rounding can produce tiny negatives
            score = max(0.0, min(1.0, raw_score))
            results.append(_chunk_to_result(chunk, score))

        logger.info(
            "vector_retrieval_done",
            user_id=str(user_id),
            top_k=top_k,
            returned=len(results),
        )
        return results


# ── Helper ────────────────────────────────────────────────────────────────────


def _chunk_to_result(chunk: Chunk, score: float) -> RetrievalResult:
    """Convert a ``Chunk`` ORM object + score into a ``RetrievalResult``."""
    meta: dict[str, Any] = chunk.chunk_metadata or {}
    return RetrievalResult(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        user_id=chunk.user_id,
        content=chunk.content,
        score=score,
        chunk_index=chunk.chunk_index,
        page_number=chunk.page_number,
        source_filename=meta.get("source_filename", "unknown"),
        chunk_metadata=meta,
    )
