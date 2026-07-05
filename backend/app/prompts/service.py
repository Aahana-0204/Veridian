"""PromptService: loads Jinja2 templates and assembles RAG prompts.

Responsibilities (SRP)
-----------------------
1. Load and cache versioned Jinja2 templates from the templates/ directory.
2. Inject retrieved chunks and conversation history into the template.
3. Truncate context intelligently when the assembled prompt would exceed the
   model's context window — prioritising the most relevant chunks and the
   most recent conversation turns.

Token counting
--------------
We use ``tiktoken`` for OpenAI models (exact token count) with a character-
based fallback (~4 chars per token) for other providers or when tiktoken is
not installed.  This avoids making tiktoken a hard dependency.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from app.schemas.rag import ChatTurn, RetrievalResult

if TYPE_CHECKING:
    from jinja2 import Template

logger = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ── Token counting ────────────────────────────────────────────────────────────


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Estimate token count for *text*.

    Uses tiktoken when available; falls back to ``len(text) // 4``.
    """
    try:
        import tiktoken

        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


# ── Template loading ──────────────────────────────────────────────────────────


@lru_cache(maxsize=8)
def _load_template(name: str) -> Template:
    """Load and cache a Jinja2 template by *name* (without extension)."""
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as exc:
        raise RuntimeError(
            "jinja2 is required for PromptService. "
            "Add it to requirements.txt or run: pip install jinja2"
        ) from exc

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    return env.get_template(f"{name}.j2")


# ── PromptService ─────────────────────────────────────────────────────────────


class PromptService:
    """Assembles the final prompt from template + chunks + history.

    Parameters
    ----------
    template_name:
        Name of the Jinja2 template file (without ``.j2`` extension).
    max_context_tokens:
        Maximum tokens to allocate to retrieved chunks in the prompt.
        When the total would exceed this, least-relevant chunks are
        dropped first.
    max_history_tokens:
        Maximum tokens for conversation history.  Oldest turns are
        dropped first when the limit is exceeded.
    model:
        LLM model name — passed to ``count_tokens`` for accurate
        tiktoken-based counting.
    """

    def __init__(
        self,
        template_name: str = "rag_v1",
        max_context_tokens: int = 4000,
        max_history_tokens: int = 1000,
        model: str = "gpt-4o-mini",
    ) -> None:
        self._template_name = template_name
        self._max_context_tokens = max_context_tokens
        self._max_history_tokens = max_history_tokens
        self._model = model

    # ── Public API ────────────────────────────────────────────────────────────

    def build_prompt(
        self,
        query: str,
        chunks: list[RetrievalResult],
        history: list[ChatTurn] | None = None,
    ) -> str:
        """Assemble and return the full prompt string.

        Chunks are already ordered by descending relevance; we preserve
        that order and drop from the tail when truncating.
        """
        history = history or []
        truncated_chunks = self._truncate_chunks(chunks)
        truncated_history = self._truncate_history(history)

        template = _load_template(self._template_name)
        prompt = template.render(
            query=query,
            chunks=truncated_chunks,
            history=truncated_history,
        )

        logger.debug(
            "prompt_assembled",
            template=self._template_name,
            chunks_in=len(chunks),
            chunks_used=len(truncated_chunks),
            history_turns=len(truncated_history),
            prompt_tokens=count_tokens(prompt, self._model),
        )
        return prompt

    # ── Private helpers ───────────────────────────────────────────────────────

    def _truncate_chunks(self, chunks: list[RetrievalResult]) -> list[RetrievalResult]:
        """Drop least-relevant chunks until total fits within token budget.

        Chunks arrive in descending relevance order; we fill from the front
        and stop when the next chunk would overflow the budget.
        """
        kept: list[RetrievalResult] = []
        used_tokens = 0
        for chunk in chunks:
            tok = count_tokens(chunk.content, self._model)
            if used_tokens + tok > self._max_context_tokens:
                logger.debug(
                    "chunk_truncated",
                    chunk_id=str(chunk.chunk_id),
                    reason="token_budget_exceeded",
                )
                break
            kept.append(chunk)
            used_tokens += tok
        return kept

    def _truncate_history(self, history: list[ChatTurn]) -> list[ChatTurn]:
        """Keep the most recent turns that fit within the history token budget.

        Works from the end of the history list (most recent) backwards.
        """
        kept: list[ChatTurn] = []
        used_tokens = 0
        for turn in reversed(history):
            tok = count_tokens(turn.content, self._model)
            if used_tokens + tok > self._max_history_tokens:
                break
            kept.append(turn)
            used_tokens += tok
        return list(reversed(kept))

    @property
    def template_name(self) -> str:
        return self._template_name

    @property
    def max_context_tokens(self) -> int:
        return self._max_context_tokens
