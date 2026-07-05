"""OpenAI generation provider via LangChain ChatOpenAI.

Default model: ``gpt-4o-mini``

Why gpt-4o-mini
---------------
- Best cost / quality ratio for RAG at this scale (~$0.15/1M input tokens).
- 128 k token context window — accommodates large retrieved context.
- Native streaming support via LangChain ``astream``.
- JSON-structured output if needed in future parts.

Why LangChain
-------------
- Consistent streaming API regardless of underlying provider.
- ``ChatOpenAI`` handles retry, timeout, and token-usage tracking.
- Swapping to Anthropic / Mistral requires only changing this module.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog

from app.generation.base import GenerationProvider

logger = structlog.get_logger(__name__)

_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
}


class OpenAIGenerationProvider(GenerationProvider):
    """LangChain-backed OpenAI chat completion provider.

    Parameters
    ----------
    api_key:
        OpenAI API key.
    model:
        OpenAI model identifier.
    temperature:
        Sampling temperature (0.0 = deterministic).
    max_tokens:
        Maximum completion tokens.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> None:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "langchain-openai is required for OpenAIGenerationProvider. "
                "Run: pip install langchain-openai"
            ) from exc

        self._model = model
        self._llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            streaming=True,
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
        """Yield tokens from the OpenAI streaming API."""
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
            "openai_complete",
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return text, prompt_tokens, completion_tokens
