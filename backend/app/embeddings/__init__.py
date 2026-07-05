"""Embeddings package public API.

Importing this package automatically registers all built-in providers
(OpenAI, SentenceTransformers) with ``EmbeddingProviderFactory`` so
that ``EmbeddingProviderFactory.create(settings)`` works without
callers needing to know which modules exist.
"""

from __future__ import annotations

# Side-effect imports: register built-in providers
import app.embeddings.openai_provider  # noqa: F401, E402
import app.embeddings.sentence_transformers_provider  # noqa: F401, E402
from app.embeddings.base import (
    EmbeddingError,
    EmbeddingProvider,
    TransientEmbeddingError,
)
from app.embeddings.batch import BatchEmbedder
from app.embeddings.factory import EmbeddingProviderFactory
from app.embeddings.retry import RetryPolicy

__all__ = [
    "EmbeddingProvider",
    "EmbeddingError",
    "TransientEmbeddingError",
    "EmbeddingProviderFactory",
    "BatchEmbedder",
    "RetryPolicy",
]
