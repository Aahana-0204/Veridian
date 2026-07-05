"""Keyword (BM25-like) retriever using PostgreSQL full-text search.

Uses ``to_tsvector`` + ``plainto_tsquery`` + ``ts_rank`` — a built-in
PostgreSQL capability that provides BM25-style tf-idf scoring without
additional infrastructure.

Score normalization
-------------------
``ts_rank`` returns a value in [0, 1] for the default normalization.
We clamp and scale it so it is comparable with vector cosine scores
for RRF fusion (the scores themselves are not used in RRF — only ranks).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.retrieval.base import AbstractRetriever
from app.retrieval.vector import _chunk_to_result
from app.schemas.rag import RetrievalResult

logger = structlog.get_logger(__name__)


class KeywordRetriever(AbstractRetriever):
    """BM25-like retrieval via PostgreSQL full-text search.

    Uses ``plainto_tsquery`` (not ``to_tsquery``) so raw user queries do
    not need boolean operators to be valid.

    Language is configurable (defaults to 'english') to handle multi-lingual
    documents.
    """

    def __init__(self, language: str = "english") -> None:
        self._language = language

    async def retrieve(
        self,
        query: str,
        user_id: uuid.UUID,
        session: AsyncSession,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Return the *top_k* keyword-matched chunks for *user_id*."""
        lang = self._language
        tsv = func.to_tsvector(lang, Chunk.content)
        tsq = func.plainto_tsquery(lang, query)
        rank_expr = func.ts_rank(tsv, tsq).label("score")

        stmt = (
            select(Chunk, rank_expr)
            .where(
                Chunk.user_id == user_id,
                tsv.op("@@")(tsq),
            )
            .order_by(rank_expr.desc())
            .limit(top_k)
        )

        rows = (await session.execute(stmt)).all()
        results: list[RetrievalResult] = []
        for row in rows:
            chunk: Chunk = row[0]
            raw_score: float = float(row[1])
            score = max(0.0, min(1.0, raw_score))
            results.append(_chunk_to_result(chunk, score))

        logger.info(
            "keyword_retrieval_done",
            user_id=str(user_id),
            top_k=top_k,
            returned=len(results),
        )
        return results
