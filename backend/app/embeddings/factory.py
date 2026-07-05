"""EmbeddingProvider factory using a registry pattern.

Design (SOLID)
--------------
- **O** — Open/Closed: adding a new provider requires only registering
  it via the ``@EmbeddingProviderFactory.register(name)`` decorator in
  its own module.  The factory itself never changes.
- **D** — Callers depend on ``EmbeddingProvider`` (the abstraction),
  not on any concrete class.

Registration happens as a side-effect of importing provider modules.
The package ``__init__.py`` imports all built-in providers to trigger
registration before the factory is first called.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

import structlog

from app.embeddings.base import EmbeddingError, EmbeddingProvider

if TYPE_CHECKING:
    from app.core.config import Settings

logger = structlog.get_logger(__name__)


class EmbeddingProviderFactory:
    """Registry-based factory for ``EmbeddingProvider`` instances.

    Usage
    -----
    Register a provider (in its own module):

    .. code-block:: python

        @EmbeddingProviderFactory.register("my-provider")
        def _create(settings: Settings) -> EmbeddingProvider:
            return MyProvider(api_key=settings.my_api_key)

    Create a provider from runtime settings:

    .. code-block:: python

        provider = EmbeddingProviderFactory.create(get_settings())

    The factory validates that the provider's output dimension matches
    ``settings.embedding_dimensions`` before returning.  A mismatch
    raises ``EmbeddingError`` with a clear remediation message.
    """

    _REGISTRY: ClassVar[dict[str, Callable[[Settings], EmbeddingProvider]]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[
        [Callable[[Settings], EmbeddingProvider]],
        Callable[[Settings], EmbeddingProvider],
    ]:
        """Decorator: register a constructor function under *name*."""

        def decorator(
            fn: Callable[[Settings], EmbeddingProvider],
        ) -> Callable[[Settings], EmbeddingProvider]:
            cls._REGISTRY[name] = fn
            logger.debug("embedding_provider_registered", name=name)
            return fn

        return decorator

    @classmethod
    def create(cls, settings: Settings) -> EmbeddingProvider:
        """Instantiate the provider selected by *settings.embedding_provider*.

        Raises
        ------
        EmbeddingError
            If the provider name is unknown, or if the provider's output
            dimension does not match ``settings.embedding_dimensions``.
        """
        name = settings.embedding_provider
        constructor = cls._REGISTRY.get(name)
        if constructor is None:
            known = sorted(cls._REGISTRY)
            raise EmbeddingError(
                f"Unknown embedding provider '{name}'. "
                f"Registered providers: {known}. "
                "Ensure the provider module is imported before calling create()."
            )

        provider = constructor(settings)

        if provider.dimensions != settings.embedding_dimensions:
            raise EmbeddingError(
                f"Provider '{name}' (model={provider.model_name!r}) produces "
                f"{provider.dimensions}-dimensional vectors, but "
                f"settings.embedding_dimensions={settings.embedding_dimensions} "
                f"and the pgvector column is Vector({settings.embedding_dimensions}). "
                "Either change EMBEDDING_PROVIDER / OPENAI_EMBEDDING_MODEL to match, "
                "or run an Alembic migration to resize the column and update "
                "EMBEDDING_DIMENSIONS in your .env."
            )

        logger.info(
            "embedding_provider_created",
            provider=name,
            model=provider.model_name,
            dimensions=provider.dimensions,
        )
        return provider

    @classmethod
    def registered_providers(cls) -> list[str]:
        """Return the names of all currently registered providers."""
        return sorted(cls._REGISTRY)
