"""Abstract base for retrieval components.

Design (SOLID)
--------------
- **I** — ``AbstractRetriever`` exposes a single method: ``retrieve``.
  Implementers are not forced to carry hybrid or re-ranking concerns.
- **L** — ``VectorRetriever``, ``KeywordRetriever``, and ``HybridRetriever``
  are all interchangeable where an ``AbstractRetriever`` is expected.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rag import RetrievalResult


class AbstractRetriever(ABC):
    """Minimal retrieval interface.

    Every retriever accepts a natural-language query and returns a ranked
    list of ``RetrievalResult`` objects, scoped to a specific user.
    """

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        user_id: uuid.UUID,
        session: AsyncSession,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Return the *top_k* most relevant chunks for *query*.

        Results must be:
        - Scoped to *user_id* — no cross-user data leakage.
        - Ordered by descending relevance (most relevant first).
        - Non-empty only when matching chunks exist.
        """
        ...
