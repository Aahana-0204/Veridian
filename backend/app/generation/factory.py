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
    - ``"ollama"``  — Local Ollama inference: free forever, no API key (default).
    - ``"groq"``    — Groq cloud LPU: free tier (30 req/min, 6k/day).
    - ``"openai"``  — OpenAI GPT models: paid.

    Add new providers by extending this function and documenting the choice
    in DECISIONS.md.
    """
    name = settings.llm_provider

    if name == "ollama":
        from app.generation.ollama_provider import OllamaGenerationProvider

        return OllamaGenerationProvider(
            base_url=settings.ollama_base_url,
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

    if name == "openai":
        from app.generation.openai_provider import OpenAIGenerationProvider

        return OpenAIGenerationProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    raise ValueError(
        f"Unknown LLM provider '{name}'. "
        "Set LLM_PROVIDER=ollama, LLM_PROVIDER=groq, or LLM_PROVIDER=openai in your .env."
    )
