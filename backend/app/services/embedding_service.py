"""EmbeddingService: orchestrates embedding generation for document chunks.

Design (SOLID)
--------------
- **S** — Single responsibility: embed a list of ``Chunk`` ORM objects
  and persist the vectors.  Status transitions and error handling live
  in the ingestion pipeline, not here.
- **D** — Depends on ``EmbeddingProvider`` (abstract), ``BatchEmbedder``
  (concrete but injectable), and ``RetryPolicy`` (concrete but injectable).
  Tests inject mock providers without touching production code.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.batch import BatchEmbedder
from app.embeddings.retry import RetryPolicy
from app.models.chunk import Chunk

logger = structlog.get_logger(__name__)


class EmbeddingService:
    """Embeds a list of chunks and writes the vectors back to the session.

    Parameters
    ----------
    provider:
        Any ``EmbeddingProvider`` implementation (OpenAI, sentence-transformers…).
    retry_policy:
        Controls per-batch retry behaviour on transient failures.
    max_concurrency:
        Maximum concurrent embedding API calls.  Passed to ``BatchEmbedder``.
    """

    def __init__(
        self,
        provider: EmbeddingProvider,
        retry_policy: RetryPolicy,
        max_concurrency: int = 3,
    ) -> None:
        self._provider = provider
        self._embedder = BatchEmbedder(
            provider=provider,
            retry_policy=retry_policy,
            max_concurrency=max_concurrency,
        )

    @property
    def provider(self) -> EmbeddingProvider:
        """Expose the underlying provider (useful for dimension checks)."""
        return self._provider

    async def embed_chunks(
        self,
        chunks: list[Chunk],
        session: AsyncSession,
    ) -> None:
        """Generate embeddings for *chunks* and persist them to the session.

        The method flushes (but does **not** commit) after writing vectors
        so that the caller retains control over the transaction boundary.

        Parameters
        ----------
        chunks:
            ORM ``Chunk`` objects whose ``content`` field will be embedded.
            The ``embedding`` column on each object is updated in-place.
        session:
            Active ``AsyncSession``.  Must already contain the chunk rows.

        Raises
        ------
        EmbeddingError
            If embedding fails after all configured retries, or for any
            non-transient error.  The caller is responsible for marking
            the parent document as ``FAILED``.
        """
        if not chunks:
            logger.debug("embed_chunks_skipped", reason="no chunks")
            return

        texts = [chunk.content for chunk in chunks]
        logger.info(
            "embedding_chunks_start",
            chunk_count=len(texts),
            model=self._provider.model_name,
            dimensions=self._provider.dimensions,
        )

        vectors = await self._embedder.embed_all(texts)

        if len(vectors) != len(chunks):
            raise EmbeddingError(
                f"Provider returned {len(vectors)} vectors for {len(chunks)} chunks. "
                "This is a provider bug — vector count must equal input count."
            )

        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector

        # Flush writes vectors to the DB within the current transaction;
        # the caller commits (or rolls back) when the full pipeline is done.
        await session.flush()
        logger.info("embedding_chunks_complete", chunk_count=len(chunks))
