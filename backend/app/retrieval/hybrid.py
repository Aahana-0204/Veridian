"""Hybrid retriever using Reciprocal Rank Fusion (RRF).

Strategy: RRF
-------------
RRF merges ranked lists from multiple retrievers without requiring
score normalization.  For each result, its RRF score is:

    score = Σ  1 / (k + rank_i)

where *k = 60* (empirically optimal from the original paper) and
*rank_i* is the 1-indexed rank in retriever *i*'s list.

Why RRF over weighted score combination:
- Vector scores (cosine similarity) and keyword scores (ts_rank) are
  not on the same scale — normalization would introduce heuristic
  weights.
- RRF is parameter-free (only k=60) and consistently outperforms
  score-level fusion in BEIR benchmarks.
- Adding a new retriever only requires appending to the ranking list.

Reference: Cormack et al. (2009) "Reciprocal Rank Fusion outperforms
Condorcet and individual Rank Learning Methods"
"""

from __future__ import annotations

import uuid
from typing import ClassVar

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.base import AbstractRetriever
from app.schemas.rag import RetrievalResult

logger = structlog.get_logger(__name__)


class HybridRetriever(AbstractRetriever):
    """Combines vector and keyword results with Reciprocal Rank Fusion.

    Parameters
    ----------
    vector_retriever:
        ``VectorRetriever`` instance.
    keyword_retriever:
        ``KeywordRetriever`` instance.
    candidate_multiplier:
        Fetch ``top_k * candidate_multiplier`` candidates from each
        retriever before fusion, then trim to *top_k* after RRF.
    rrf_k:
        The *k* constant in the RRF formula (default: 60).
    """

    RRF_K: ClassVar[int] = 60

    def __init__(
        self,
        vector_retriever: AbstractRetriever,
        keyword_retriever: AbstractRetriever,
        candidate_multiplier: int = 4,
        rrf_k: int = RRF_K,
    ) -> None:
        self._vector = vector_retriever
        self._keyword = keyword_retriever
        self._candidate_multiplier = candidate_multiplier
        self._rrf_k = rrf_k

    async def retrieve(
        self,
        query: str,
        user_id: uuid.UUID,
        session: AsyncSession,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Run both retrievers and fuse via RRF, returning *top_k* results."""
        candidates = top_k * self._candidate_multiplier

        # Run retrievers concurrently
        import asyncio

        vector_results, keyword_results = await asyncio.gather(
            self._vector.retrieve(query, user_id, session, top_k=candidates),
            self._keyword.retrieve(query, user_id, session, top_k=candidates),
        )

        fused = self._rrf_fuse([vector_results, keyword_results])
        final = fused[:top_k]

        logger.info(
            "hybrid_retrieval_done",
            user_id=str(user_id),
            vector_candidates=len(vector_results),
            keyword_candidates=len(keyword_results),
            fused=len(fused),
            returned=len(final),
        )
        return final

    # ── RRF implementation ────────────────────────────────────────────────────

    def _rrf_fuse(self, rankings: list[list[RetrievalResult]]) -> list[RetrievalResult]:
        """Merge ranked lists using Reciprocal Rank Fusion.

        Returns results sorted by descending RRF score.  The ``score``
        field on each returned ``RetrievalResult`` is replaced with the
        RRF score (normalized to [0,1] for consistency).
        """
        rrf_scores: dict[uuid.UUID, float] = {}
        result_map: dict[uuid.UUID, RetrievalResult] = {}

        for ranking in rankings:
            for rank, result in enumerate(ranking):
                cid = result.chunk_id
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (
                    self._rrf_k + rank + 1
                )
                result_map[cid] = result

        # Sort by descending RRF score
        sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)

        # Normalize scores to [0, 1] so they stay in the declared range
        max_score = rrf_scores[sorted_ids[0]] if sorted_ids else 1.0

        return [
            result_map[cid].model_copy(update={"score": rrf_scores[cid] / max_score})
            for cid in sorted_ids
        ]
