"""Generation provider factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.generation.base import GenerationProvider

if TYPE_CHECKING:
    from app.core.config import Settings


def build_generation_provider(settings: Settings) -> GenerationProvider:
    """Instantiate the configured generation provider.

    Supported providers
    -------------------
    - ``"openai"``  — OpenAI GPT models (paid).
    - ``"groq"``    — Groq LPU inference (free tier, recommended for dev).

    Add new providers by extending this function and documenting the choice
    in DECISIONS.md.
    """
    name = settings.llm_provider

    if name == "openai":
        from app.generation.openai_provider import OpenAIGenerationProvider

        return OpenAIGenerationProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    if name == "groq":
        from app.generation.groq_provider import GroqGenerationProvider

        return GroqGenerationProvider(
            api_key=settings.groq_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    raise ValueError(
        f"Unknown LLM provider '{name}'. "
        "Set LLM_PROVIDER=openai or LLM_PROVIDER=groq in your .env."
    )
