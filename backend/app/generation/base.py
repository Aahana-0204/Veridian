"""Abstract generation provider interface + shared types.

Design (SOLID)
--------------
- **I** — Minimal interface: ``astream`` for streaming, ``acomplete``
  for one-shot.  Providers implement both; callers choose one.
- **L** — Any ``GenerationProvider`` substitutes for any other at the
  call site with identical semantics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class GenerationProvider(ABC):
    """Abstract contract for LLM generation back-ends."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Canonical model identifier string."""
        ...

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Maximum tokens the model accepts (input + output)."""
        ...

    @abstractmethod
    async def astream(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncGenerator[str, None]:
        """Yield response tokens one by one.

        Parameters
        ----------
        system_prompt:
            Injected as the ``system`` role message.
        user_prompt:
            The assembled RAG prompt (chunks + history + question).

        Yields
        ------
        str
            Successive response tokens / text chunks.
        """
        # Make this a valid async generator body even in ABC
        return  # pragma: no cover
        yield  # pragma: no cover

    @abstractmethod
    async def acomplete(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, int, int]:
        """Return ``(response_text, prompt_tokens, completion_tokens)``.

        Use when the caller needs the full response at once (e.g. tests).
        """
        ...
