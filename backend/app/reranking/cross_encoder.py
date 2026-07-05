"""Cross-encoder re-ranker via sentence-transformers.

A cross-encoder jointly encodes (query, chunk) pairs and produces a
single relevance score — significantly more accurate than bi-encoder
cosine similarity but O(k) times slower (one inference pass per pair).

Inference runs in a thread-pool executor to avoid blocking the event loop.
The model is loaded once at construction time.

Default model
-------------
``cross-encoder/ms-marco-MiniLM-L-6-v2``

- Trained on MS MARCO passage re-ranking (650 k queries).
- ~22 M parameters; fast enough for <50 candidates on CPU.
- Returns raw logits (higher = more relevant); we normalize to [0,1].
"""

from __future__ import annotations

import asyncio

import structlog

from app.reranking.base import Reranker
from app.schemas.rag import RetrievalResult

logger = structlog.get_logger(__name__)


class CrossEncoderReranker(Reranker):
    """Re-ranks candidates using a sentence-transformers cross-encoder.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier for a CrossEncoder model.
    """

    def __init__(
        self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder  # lazy import

            self._model = CrossEncoder(model_name)
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for CrossEncoderReranker. "
                "Install it or set RERANKER_ENABLED=false."
            ) from exc
        self._model_name = model_name

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_n: int,
    ) -> list[RetrievalResult]:
        """Score all (query, chunk) pairs and return the *top_n* highest."""
        if not results:
            return []

        pairs = [(query, r.content) for r in results]
        loop = asyncio.get_running_loop()

        raw_scores: list[float] = await loop.run_in_executor(
            None,
            lambda: self._model.predict(pairs).tolist(),
        )

        # Sort by score descending, normalize to [0,1]
        scored = sorted(
            zip(results, raw_scores, strict=False), key=lambda x: x[1], reverse=True
        )
        top = scored[:top_n]

        if top:
            max_s = top[0][1]
            min_s = top[-1][1]
            span = max_s - min_s if max_s != min_s else 1.0
            reranked = [
                r.model_copy(update={"score": (s - min_s) / span}) for r, s in top
            ]
        else:
            reranked = [r for r, _ in top]

        logger.info(
            "cross_encoder_rerank_done",
            model=self._model_name,
            candidates=len(results),
            returned=len(reranked),
        )
        return reranked
