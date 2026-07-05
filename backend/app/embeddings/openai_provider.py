"""OpenAI embedding provider.

Uses ``text-embedding-3-small`` by default (1536 dimensions), which
exactly matches the pgvector ``Vector(1536)`` column created in Part 2
— no Alembic migration is required.

Supported models and their dimensions:

+----------------------------+------------+
| Model                      | Dimensions |
+============================+============+
| text-embedding-3-small     | 1536       |
| text-embedding-ada-002     | 1536       |
| text-embedding-3-large     | 3072       |
+----------------------------+------------+

Important: ``text-embedding-3-large`` (3072 dims) and any other model
whose dimension differs from the column size will be rejected by the
factory's dimension validation.
"""

from __future__ import annotations

import structlog

from app.embeddings.base import (
    EmbeddingError,
    EmbeddingProvider,
    TransientEmbeddingError,
)

logger = structlog.get_logger(__name__)

# Model → output dimension (add new models here as OpenAI releases them)
_MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
    "text-embedding-3-large": 3072,
}


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI Embeddings API provider.

    The ``openai`` package is imported lazily inside ``__init__`` so
    that the rest of the codebase remains importable even when the
    package is not installed (e.g., in environments using only the
    sentence-transformers back-end).

    Parameters
    ----------
    api_key:
        OpenAI API key.  Never logged or exposed in error messages.
    model:
        One of the models listed in ``_MODEL_DIMENSIONS``.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
    ) -> None:
        if model not in _MODEL_DIMENSIONS:
            raise EmbeddingError(
                f"Unknown OpenAI embedding model '{model}'. "
                f"Known models: {sorted(_MODEL_DIMENSIONS)}"
            )
        if not api_key:
            raise EmbeddingError(
                "OPENAI_API_KEY is required when using the openai embedding provider."
            )

        try:
            from openai import AsyncOpenAI  # lazy import
        except ImportError as exc:
            raise EmbeddingError(
                "The 'openai' package is not installed.  "
                "Add it to requirements.txt or run: pip install openai"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimensions = _MODEL_DIMENSIONS[model]


# ── Factory registration ──────────────────────────────────────────────────────

# Imported last to avoid circular imports at module level
from app.embeddings.factory import EmbeddingProviderFactory  # noqa: E402


@EmbeddingProviderFactory.register("openai")
def _create_openai_provider(settings: object) -> OpenAIEmbeddingProvider:  # type: ignore[type-arg]
    from app.core.config import Settings

    s: Settings = settings  # type: ignore[assignment]
    return OpenAIEmbeddingProvider(
        api_key=s.openai_api_key,
        model=s.openai_embedding_model,
    )

    # ── EmbeddingProvider interface ───────────────────────────────────────────

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def max_batch_size(self) -> int:
        # OpenAI allows up to 2048 inputs per request; stay conservative.
        return 512

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Call the OpenAI Embeddings API for a single batch."""
        from openai import APIConnectionError, APITimeoutError, RateLimitError

        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=texts,
                encoding_format="float",
            )
            # Sort by index to guarantee output order matches input order
            sorted_data = sorted(response.data, key=lambda item: item.index)
            vectors = [item.embedding for item in sorted_data]
            logger.debug(
                "openai_embed_batch_ok",
                model=self._model,
                texts=len(texts),
                tokens=response.usage.total_tokens if response.usage else None,
            )
            return vectors
        except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
            raise TransientEmbeddingError(
                f"OpenAI transient error ({type(exc).__name__}): {exc}"
            ) from exc
        except Exception as exc:
            raise EmbeddingError(
                f"OpenAI embedding error ({type(exc).__name__}): {exc}"
            ) from exc
