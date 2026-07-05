"""GenerationService: streaming LLM generation with citation extraction.

Design (SOLID)
--------------
- **S** — Responsible only for: building the system prompt, calling the
  provider, extracting citations, and assembling ``GenerationResult``.
- **D** — Depends on ``GenerationProvider`` ABC — not on OpenAI directly.

Citation extraction
-------------------
The prompt template instructs the LLM to cite chunks using ``[CHUNK_N]``
references.  After generation, we scan the response for these markers and
map them back to the original ``RetrievalResult`` list.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator

import structlog

from app.generation.base import GenerationProvider
from app.schemas.rag import Citation, GenerationResult, RetrievalResult

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are Veridian, a precise and helpful document assistant. "
    "Answer questions based only on the provided document excerpts. "
    "Cite your sources using [CHUNK_N] notation. "
    "If the answer is not in the documents, say so clearly."
)

_CITATION_RE = re.compile(r"\[CHUNK_(\d+)\]")


class GenerationService:
    """Wraps a ``GenerationProvider`` with streaming and citation extraction.

    Parameters
    ----------
    provider:
        Any ``GenerationProvider`` implementation.
    """

    def __init__(self, provider: GenerationProvider) -> None:
        self._provider = provider

    # ── Public API ────────────────────────────────────────────────────────────

    async def stream_generate(
        self,
        assembled_prompt: str,
        chunks: list[RetrievalResult],
    ) -> AsyncGenerator[str | GenerationResult, None]:
        """Stream tokens, then yield a final ``GenerationResult``.

        Callers should iterate the generator and handle two item types:

        - ``str``              — a response token to forward to the client
        - ``GenerationResult`` — the final structured result (always last)

        Parameters
        ----------
        assembled_prompt:
            The full prompt string from ``PromptService.build_prompt()``.
        chunks:
            The ordered ``RetrievalResult`` list used to build the prompt
            (needed for citation resolution).
        """
        accumulated: list[str] = []

        async for token in self._provider.astream(_SYSTEM_PROMPT, assembled_prompt):
            accumulated.append(token)
            yield token

        full_response = "".join(accumulated)
        citations = _extract_citations(full_response, chunks)

        from app.prompts.service import count_tokens

        prompt_tokens = count_tokens(assembled_prompt, self._provider.model_name)
        completion_tokens = count_tokens(full_response, self._provider.model_name)

        logger.info(
            "generation_stream_complete",
            model=self._provider.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            citations=len(citations),
        )

        yield GenerationResult(
            answer=full_response,
            citations=citations,
            model=self._provider.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def generate(
        self,
        assembled_prompt: str,
        chunks: list[RetrievalResult],
    ) -> GenerationResult:
        """Non-streaming generation — returns the complete result at once.

        Useful for batch processing and testing.
        """
        text, prompt_tokens, completion_tokens = await self._provider.acomplete(
            _SYSTEM_PROMPT, assembled_prompt
        )
        citations = _extract_citations(text, chunks)

        logger.info(
            "generation_complete",
            model=self._provider.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            citations=len(citations),
        )
        return GenerationResult(
            answer=text,
            citations=citations,
            model=self._provider.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


# ── Citation extraction ───────────────────────────────────────────────────────


def _extract_citations(response: str, chunks: list[RetrievalResult]) -> list[Citation]:
    """Parse ``[CHUNK_N]`` references from *response* and resolve to chunks.

    Returns citations in the order they appear in the response, deduped.
    """
    seen: set[int] = set()
    citations: list[Citation] = []

    for match in _CITATION_RE.finditer(response):
        n = int(match.group(1))
        idx = n - 1  # template uses 1-indexed [CHUNK_N]
        if idx in seen or not (0 <= idx < len(chunks)):
            continue
        seen.add(idx)
        chunk = chunks[idx]
        citations.append(
            Citation(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                snippet=chunk.content[:200],
                source_filename=chunk.source_filename,
                score=chunk.score,
            )
        )

    return citations
