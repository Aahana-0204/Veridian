"""No-op reranker — pass-through when re-ranking is disabled."""

from __future__ import annotations

from app.reranking.base import Reranker
from app.schemas.rag import RetrievalResult


class NoopReranker(Reranker):
    """Returns the first *top_n* results unchanged.

    Used when ``RERANKER_ENABLED=false`` so the ``RetrievalService``
    never needs to branch on whether re-ranking is configured.
    """

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_n: int,
    ) -> list[RetrievalResult]:
        return results[:top_n]
