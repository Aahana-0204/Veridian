"""Embedding provider abstraction: base class and exception hierarchy.

Design (SOLID)
--------------
- **S** — Providers only generate embedding vectors; batching and retry
  are separate responsibilities handled in ``batch.py`` and ``retry.py``.
- **I** — Interface is kept minimal: callers only need ``embed_batch``
  and the ``dimensions`` / ``model_name`` properties.
- **L** — Any concrete provider is a valid substitute for any other
  (same contract, same exception types).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# ── Exception hierarchy ───────────────────────────────────────────────────────


class EmbeddingError(Exception):
    """Non-retryable embedding failure.

    Raised for permanent errors such as invalid input, authentication
    failures, or unexpected provider responses.  The caller must *not*
    retry automatically.
    """


class TransientEmbeddingError(Exception):
    """Retryable embedding failure.

    Raised for transient conditions such as rate limits, connection
    timeouts, or temporary server errors.  The caller *should* retry
    with exponential back-off.
    """


# ── Abstract provider ─────────────────────────────────────────────────────────


class EmbeddingProvider(ABC):
    """Abstract contract for all embedding back-ends.

    Concrete implementations wrap a specific model / API and translate
    provider-specific errors into ``EmbeddingError`` /
    ``TransientEmbeddingError``.  They must be stateless beyond
    initialization (no mutable instance state that callers depend on).
    """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Number of floats in each output vector (constant per instance)."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Canonical model identifier (e.g. ``"text-embedding-3-small"``)."""
        ...

    @property
    def max_batch_size(self) -> int:
        """Maximum number of texts per single ``embed_batch`` call.

        Subclasses should override this to reflect API limits or memory
        constraints.  Default: 100.
        """
        return 100

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in a single round-trip.

        Parameters
        ----------
        texts:
            Non-empty list of strings.  ``len(texts) <= max_batch_size``
            is guaranteed by ``BatchEmbedder``.

        Returns
        -------
        list[list[float]]
            Parallel list of embedding vectors, same length as *texts*.

        Raises
        ------
        EmbeddingError
            Permanent, non-retryable failure.
        TransientEmbeddingError
            Temporary failure; the caller should retry.
        """
        ...
