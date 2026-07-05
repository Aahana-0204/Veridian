"""Abstract reranker interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.rag import RetrievalResult


class Reranker(ABC):
    """Re-orders a candidate list by a more expensive relevance signal.

    Design (SOLID)
    --------------
    - **S** — Only re-ordering; no retrieval or DB access.
    - **L** — ``NoopReranker`` and ``CrossEncoderReranker`` are interchangeable.
    - **I** — Single method interface; implementations need nothing else.
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_n: int,
    ) -> list[RetrievalResult]:
        """Re-rank *results* by relevance to *query* and return *top_n*.

        Parameters
        ----------
        query:
            The original user query.
        results:
            Candidate results from the retriever (unmodified).
        top_n:
            Number of results to return.

        Returns
        -------
        list[RetrievalResult]
            *top_n* results in descending relevance order.
        """
        ...
