"""Groq generation provider via LangChain ChatGroq.

Why Groq (free tier)
--------------------
- Free tier: up to 30 req/min, 6,000 req/day with no credit card required.
- Ultra-low latency inference on LPU hardware (often 10x faster than OpenAI).
- Supports Llama 3.3 70B, Llama 3.1 8B, Mixtral, Gemma — all open-weight.
- Drop-in replacement: same LangChain streaming API as OpenAI provider.

Default model: ``llama-3.1-8b-instant``
- 128 k context window.
- Fastest Groq model; ideal for RAG where retrieved context is well-structured.
- Upgrade to ``llama-3.3-70b-versatile`` for higher answer quality at the
  cost of slightly more latency (still free-tier eligible).

Sign up at https://console.groq.com — API key is free.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog

from app.generation.base import GenerationProvider

logger = structlog.get_logger(__name__)

_CONTEXT_WINDOWS: dict[str, int] = {
    "llama-3.1-8b-instant": 128_000,
    "llama-3.3-70b-versatile": 128_000,
    "llama-3.1-70b-versatile": 128_000,
    "mixtral-8x7b-32768": 32_768,
    "gemma2-9b-it": 8_192,
}


class GroqGenerationProvider(GenerationProvider):
    """LangChain-backed Groq chat completion provider.

    Parameters
    ----------
    api_key:
        Groq API key (free at console.groq.com).
    model:
        Groq model identifier.
    temperature:
        Sampling temperature (0.0 = deterministic).
    max_tokens:
        Maximum completion tokens.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> None:
        try:
            from langchain_groq import ChatGroq
        except ImportError as exc:
            raise RuntimeError(
                "langchain-groq is required for GroqGenerationProvider. "
                "Run: pip install langchain-groq"
            ) from exc

        self._model = model
        self._llm = ChatGroq(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
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
        """Yield tokens from the Groq streaming API."""
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
            "groq_complete",
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return text, prompt_tokens, completion_tokens
