"""High-level RetrievalService: orchestrates retriever + optional reranker.

Design (SOLID)
--------------
- **S** — Coordinates retrieval and re-ranking; does not implement either.
- **D** — Depends on ``AbstractRetriever`` and ``Reranker`` abstractions.
  Callers inject concrete instances; swapping strategies requires only a
  config change.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.base import AbstractRetriever
from app.schemas.rag import RetrievalResult

if TYPE_CHECKING:
    from app.reranking.base import Reranker

logger = structlog.get_logger(__name__)


class RetrievalService:
    """Orchestrates retrieval and optional re-ranking into a single call.

    Parameters
    ----------
    retriever:
        Any ``AbstractRetriever`` (vector, keyword, or hybrid).
    reranker:
        Any ``Reranker`` — use ``NoopReranker`` to disable re-ranking.
    top_k:
        Number of chunks to return to the caller.
    reranker_top_n_multiplier:
        Fetch ``top_k * multiplier`` candidates before re-ranking, then
        trim to ``top_k``.  Ignored when using ``NoopReranker``.
    """

    def __init__(
        self,
        retriever: AbstractRetriever,
        reranker: Reranker,
        top_k: int = 5,
        reranker_top_n_multiplier: int = 4,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._top_k = top_k
        self._reranker_top_n_multiplier = reranker_top_n_multiplier

    async def retrieve(
        self,
        query: str,
        user_id: uuid.UUID,
        session: AsyncSession,
    ) -> list[RetrievalResult]:
        """Retrieve and (optionally) re-rank chunks for *query*.

        Parameters
        ----------
        query:
            Natural-language query string.
        user_id:
            Results are strictly scoped to this user's documents.
        session:
            Active ``AsyncSession`` for database access.

        Returns
        -------
        list[RetrievalResult]
            Up to ``top_k`` results, ordered by descending relevance.
        """
        # Fetch more candidates when re-ranking is active
        candidates = self._top_k * self._reranker_top_n_multiplier
        raw_results = await self._retriever.retrieve(
            query, user_id, session, top_k=candidates
        )

        reranked = await self._reranker.rerank(
            query=query,
            results=raw_results,
            top_n=self._top_k,
        )

        logger.info(
            "retrieval_service_done",
            user_id=str(user_id),
            raw=len(raw_results),
            returned=len(reranked),
        )
        return reranked
