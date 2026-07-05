"""Async retry policy with exponential back-off and jitter.

Design (SOLID)
--------------
- **S** — ``RetryPolicy`` has exactly one responsibility: deciding
  *when* and *how long* to wait between attempts.  It knows nothing
  about what is being retried.
- **O** — Behaviour is configured through constructor arguments;
  new back-off strategies are added by composing a different instance.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Coroutine
from typing import TypeVar

import structlog

from app.embeddings.base import EmbeddingError, TransientEmbeddingError

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class RetryPolicy:
    """Executes an async callable with exponential back-off on transient errors.

    Parameters
    ----------
    max_attempts:
        Total number of attempts (first try + retries).
    base_delay:
        Initial sleep in seconds after the first failure.
    max_delay:
        Upper bound on sleep, regardless of attempt count.
    jitter:
        When ``True``, adds ±25 % random jitter to avoid thundering-herd.

    Behaviour
    ---------
    - ``TransientEmbeddingError`` → sleep and retry (up to *max_attempts*)
    - ``EmbeddingError``          → re-raise immediately (no retry)
    - Any other ``Exception``     → wrap in ``EmbeddingError`` and re-raise
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: bool = True,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    async def execute(
        self,
        coro_fn: Callable[[], Coroutine[None, None, T]],
    ) -> T:
        """Run *coro_fn* with automatic retries on transient errors.

        Parameters
        ----------
        coro_fn:
            Zero-argument callable that returns a *fresh* coroutine each
            invocation (must be re-callable, not a pre-created coroutine).

        Raises
        ------
        EmbeddingError
            After all retries are exhausted, or on a non-transient failure.
        """
        last_exc: BaseException | None = None

        for attempt in range(self.max_attempts):
            try:
                return await coro_fn()
            except TransientEmbeddingError as exc:
                last_exc = exc
                if attempt < self.max_attempts - 1:
                    delay = self._compute_delay(attempt)
                    logger.warning(
                        "embedding_retry",
                        attempt=attempt + 1,
                        max_attempts=self.max_attempts,
                        delay_s=round(delay, 2),
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "embedding_max_retries_exceeded",
                        max_attempts=self.max_attempts,
                        error=str(exc),
                    )
            except EmbeddingError:
                raise  # permanent — propagate immediately
            except Exception as exc:
                raise EmbeddingError(
                    f"Unexpected error from embedding provider: {exc}"
                ) from exc

        raise EmbeddingError(
            f"Embedding failed after {self.max_attempts} attempt(s)."
        ) from last_exc

    def _compute_delay(self, attempt: int) -> float:
        """Return the sleep duration for the given 0-indexed *attempt*."""
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay *= random.uniform(0.75, 1.25)
        return delay
