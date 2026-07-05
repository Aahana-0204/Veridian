"""FastAPI dependency for the singleton EmbeddingProvider.

The provider is constructed once per process (``lru_cache``) from the
application settings.  Tests override ``get_embedding_provider`` via
``app.dependency_overrides`` to inject a mock provider.
"""

from __future__ import annotations

from functools import lru_cache

import structlog

# Ensure providers are registered before first call
import app.embeddings.openai_provider  # noqa: F401
import app.embeddings.sentence_transformers_provider  # noqa: F401
from app.core.config import get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import EmbeddingProviderFactory

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def _build_provider() -> EmbeddingProvider:
    """Construct and cache the configured provider (called once at startup)."""
    return EmbeddingProviderFactory.create(get_settings())


def get_embedding_provider() -> EmbeddingProvider:
    """FastAPI dependency: return the cached ``EmbeddingProvider`` singleton."""
    return _build_provider()
