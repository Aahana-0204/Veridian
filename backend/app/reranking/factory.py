"""Reranker factory: build from application settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.reranking.base import Reranker

if TYPE_CHECKING:
    from app.core.config import Settings


def build_reranker(settings: Settings) -> Reranker:
    """Construct the configured reranker.

    When ``settings.reranker_enabled`` is ``False``, returns a
    ``NoopReranker`` so the calling code never needs to branch.
    """
    if not settings.reranker_enabled:
        from app.reranking.noop import NoopReranker

        return NoopReranker()

    from app.reranking.cross_encoder import CrossEncoderReranker

    return CrossEncoderReranker(model_name=settings.reranker_model)
