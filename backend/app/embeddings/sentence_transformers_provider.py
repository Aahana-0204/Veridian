"""Sentence-Transformers local embedding provider.

Uses ``sentence-transformers`` (HuggingFace) to generate embeddings
entirely on-device — no API key required.

Default model: ``all-MiniLM-L6-v2`` (384 dimensions).

⚠️  DIMENSION MISMATCH WARNING
------------------------------
The pgvector ``chunks.embedding`` column was created with ``Vector(1536)``
in Part 2, matching the OpenAI ``text-embedding-3-small`` default.
``all-MiniLM-L6-v2`` produces **384**-dimensional vectors — a different
size.

If you switch ``EMBEDDING_PROVIDER=sentence-transformers``, you **must**:

1. Also set ``EMBEDDING_DIMENSIONS=384`` in your ``.env``.
2. Run the provided Alembic migration to resize the column:

   .. code-block:: bash

       alembic upgrade head  # migration: alter_embedding_dim_384

The factory will reject a dimension mismatch with a clear error before
any data is written.
"""

from __future__ import annotations

import asyncio

import structlog

from app.embeddings.base import EmbeddingError, EmbeddingProvider

logger = structlog.get_logger(__name__)


class SentenceTransformerProvider(EmbeddingProvider):
    """Local embedding provider backed by ``sentence-transformers``.

    Inference runs in a thread-pool executor so it does not block the
    event loop.  The model is loaded once at construction time; subsequent
    calls are fast.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier, e.g. ``"all-MiniLM-L6-v2"``.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # lazy import
        except ImportError as exc:
            raise EmbeddingError(
                "The 'sentence-transformers' package is not installed.  "
                "Run: pip install sentence-transformers"
            ) from exc

        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise EmbeddingError(
                f"Could not determine embedding dimension for model '{model_name}'"
            )
        self._dimensions: int = dim


# ── Factory registration ──────────────────────────────────────────────────────

from app.embeddings.factory import EmbeddingProviderFactory  # noqa: E402


@EmbeddingProviderFactory.register("sentence-transformers")
def _create_st_provider(settings: object) -> SentenceTransformerProvider:  # type: ignore[type-arg]
    from app.core.config import Settings

    s: Settings = settings  # type: ignore[assignment]
    return SentenceTransformerProvider(model_name=s.sentence_transformer_model)

    # ── EmbeddingProvider interface ───────────────────────────────────────────

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def max_batch_size(self) -> int:
        # Local model — constrained by RAM / VRAM, not API limits.
        return 64

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Run inference in a thread-pool executor (non-blocking)."""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._model.encode(
                    texts,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).tolist(),
            )
            logger.debug(
                "st_embed_batch_ok",
                model=self._model_name,
                texts=len(texts),
            )
            return result  # type: ignore[return-value]
        except Exception as exc:
            raise EmbeddingError(
                f"SentenceTransformer error ({type(exc).__name__}): {exc}"
            ) from exc
