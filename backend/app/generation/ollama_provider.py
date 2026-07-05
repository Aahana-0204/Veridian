"""Ollama generation provider via LangChain ChatOllama.

Why Ollama — truly free forever
--------------------------------
- Runs models **locally** — no API key, no account, no rate limits, no cost ever.
- Completely offline after the one-time model pull.
- Models run on CPU (works on any machine) or GPU if available.
- Docker-compose includes an ``ollama`` service so no local install is needed.
- Hundreds of open-weight models: Llama 3.2, Mistral, Phi-3, Gemma 2, etc.

Default model: ``llama3.2:3b``
- ~2 GB download, runs well on CPU (4+ GB RAM).
- Good quality for RAG: instruction-tuned, 128k context window.
- Upgrade to ``llama3.2`` (8B) or ``mistral`` (7B) for higher quality.

Quickstart (Docker Compose):
    docker compose up ollama          # starts the Ollama server
    docker compose exec ollama ollama pull llama3.2:3b   # download model once

Or standalone:
    ollama pull llama3.2:3b && ollama serve
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog

from app.generation.base import GenerationProvider

logger = structlog.get_logger(__name__)

_CONTEXT_WINDOWS: dict[str, int] = {
    "llama3.2:3b": 128_000,
    "llama3.2": 128_000,
    "llama3.1:8b": 128_000,
    "llama3.1": 128_000,
    "mistral": 32_768,
    "mistral-nemo": 128_000,
    "phi3:mini": 128_000,
    "phi3": 128_000,
    "gemma2:2b": 8_192,
    "gemma2": 8_192,
    "tinyllama": 2_048,
}


class OllamaGenerationProvider(GenerationProvider):
    """LangChain-backed Ollama local inference provider.

    Parameters
    ----------
    base_url:
        Ollama server URL. Defaults to ``http://localhost:11434`` (or the
        ``ollama`` Docker Compose service when running in containers).
    model:
        Ollama model name, e.g. ``"llama3.2:3b"``.
        Pull the model first: ``ollama pull llama3.2:3b``
    temperature:
        Sampling temperature (0.0 = deterministic).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:3b",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> None:
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise RuntimeError(
                "langchain-ollama is required for OllamaGenerationProvider. "
                "Run: pip install langchain-ollama"
            ) from exc

        self._model = model
        self._llm = ChatOllama(
            base_url=base_url,
            model=model,
            temperature=temperature,
            num_predict=max_tokens,
        )
        self._context_window = _CONTEXT_WINDOWS.get(model, 128_000)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def context_window(self) -> int:
        return self._context_window

    async def astream(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncGenerator[str, None]:
        """Yield tokens from the local Ollama server."""
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        async for chunk in self._llm.astream(messages):
            content = chunk.content
            if isinstance(content, str) and content:
                yield content

    async def acomplete(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, int, int]:
        """Return full response text and token usage."""
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = await self._llm.ainvoke(messages)
        text: str = response.content if isinstance(response.content, str) else ""
        usage = response.usage_metadata or {}
        prompt_tokens: int = usage.get("input_tokens", 0)
        completion_tokens: int = usage.get("output_tokens", 0)

        logger.info(
            "ollama_complete",
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return text, prompt_tokens, completion_tokens
