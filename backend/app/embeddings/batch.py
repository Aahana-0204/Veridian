"""Concurrent batch embedder: splits texts into provider-sized batches.

Design (SOLID)
--------------
- **S** — ``BatchEmbedder`` only handles splitting and concurrency; it
  delegates API calls to ``EmbeddingProvider`` and retry semantics to
  ``RetryPolicy``.
- **D** — Depends on the ``EmbeddingProvider`` abstraction, not on any
  concrete provider class.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import structlog

from app.embeddings.base import EmbeddingProvider
from app.embeddings.retry import RetryPolicy

logger = structlog.get_logger(__name__)


class BatchEmbedder:
    """Embeds an arbitrary number of texts using a bounded concurrency pool.

    Workflow
    --------
    1. Split *texts* into chunks of ``provider.max_batch_size``.
    2. Schedule all chunks as concurrent tasks, bounded by *max_concurrency*.
    3. Each chunk call is wrapped in ``retry_policy.execute`` for back-off.
    4. Results are reassembled in the **original input order**.

    Parameters
    ----------
    provider:
        Any ``EmbeddingProvider`` implementation.
    retry_policy:
        ``RetryPolicy`` governing per-batch retry behaviour.
    max_concurrency:
        Maximum concurrent embedding API calls.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        retry_policy: RetryPolicy,
        max_concurrency: int = 3,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._provider = provider
        self._retry_policy = retry_policy
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def embed_all(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed every text in *texts*, returning vectors in the same order.

        Returns ``[]`` immediately for empty input without any provider call.
        """
        if not texts:
            return []

        batches = self._make_batches(list(texts))
        logger.info(
            "batch_embed_start",
            total_texts=len(texts),
            num_batches=len(batches),
            batch_size=self._provider.max_batch_size,
        )

        batch_results: list[list[list[float]]] = await asyncio.gather(
            *[self._embed_one_batch(batch) for batch in batches]
        )

        # Flatten in order: [[v1,v2], [v3,v4]] → [v1, v2, v3, v4]
        return [vec for batch_vecs in batch_results for vec in batch_vecs]

    def _make_batches(self, texts: list[str]) -> list[list[str]]:
        """Split *texts* into sub-lists of at most ``max_batch_size`` items."""
        size = self._provider.max_batch_size
        return [texts[i : i + size] for i in range(0, len(texts), size)]

    async def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        """Embed a single batch under the semaphore and retry policy."""
        async with self._semaphore:
            # Capture `batch` with default arg to avoid late-binding in the closure
            async def _call(b: list[str] = batch) -> list[list[float]]:
                return await self._provider.embed_batch(b)

            result = await self._retry_policy.execute(_call)
            logger.debug("batch_embed_chunk_done", chunk_size=len(batch))
            return result
