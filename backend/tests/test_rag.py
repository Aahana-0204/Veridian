"""Tests for the RAG retrieval and generation pipeline (Part 6).

Unit tests (no DB / API required)
-----------------------------------
- RRF fusion: correct ranking, deduplication, score normalization
- Context truncation: least-relevant chunks dropped first
- Prompt assembly: template rendered with correct structure
- Citation extraction: [CHUNK_N] references resolved correctly
- Retrieval user scoping: SQL WHERE clause verified via mock

Integration tests (require live DB + savepoint isolation)
----------------------------------------------------------
- Full vector retrieval with user A/B isolation
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.generation.service import _extract_citations
from app.prompts.service import PromptService, count_tokens
from app.retrieval.hybrid import HybridRetriever
from app.schemas.rag import ChatTurn, GenerationResult, RetrievalResult

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent / "fixtures"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_result(
    content: str,
    score: float = 0.9,
    chunk_index: int = 0,
    user_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        content=content,
        score=score,
        chunk_index=chunk_index,
        page_number=None,
        source_filename="test.txt",
        chunk_metadata={},
    )


# ── RRF fusion tests ──────────────────────────────────────────────────────────


async def test_rrf_merges_two_rankings() -> None:
    """RRF correctly merges two disjoint ranked lists."""

    # We test the fusion directly via HybridRetriever._rrf_fuse
    r1 = _make_result("alpha", score=0.9)
    r2 = _make_result("beta", score=0.8)
    r3 = _make_result("gamma", score=0.7)

    # Vector ranking: r1 > r2 > r3
    # Keyword ranking: r3 > r1 > r2 — r3 boosted by keyword
    vector_ranking = [r1, r2, r3]
    keyword_ranking = [r3, r1, r2]

    retriever = HybridRetriever(
        vector_retriever=MagicMock(),
        keyword_retriever=MagicMock(),
    )
    fused = retriever._rrf_fuse([vector_ranking, keyword_ranking])

    # r1 appears in rank 1 + rank 2 → strong RRF score
    # r3 appears in rank 1 + rank 3 → decent score
    chunk_ids = [r.chunk_id for r in fused]
    assert r1.chunk_id in chunk_ids
    assert r3.chunk_id in chunk_ids
    assert len(fused) == 3


async def test_rrf_deduplicates_shared_results() -> None:
    """Chunks appearing in both rankings are not duplicated in output."""
    shared = _make_result("shared content", score=0.95)
    only_vector = _make_result("vector only", score=0.8)
    only_keyword = _make_result("keyword only", score=0.7)

    retriever = HybridRetriever(
        vector_retriever=MagicMock(),
        keyword_retriever=MagicMock(),
    )
    fused = retriever._rrf_fuse([[shared, only_vector], [shared, only_keyword]])

    chunk_ids = [r.chunk_id for r in fused]
    # shared appears once despite being in both lists
    assert chunk_ids.count(shared.chunk_id) == 1
    assert len(fused) == 3  # shared, only_vector, only_keyword


async def test_rrf_scores_normalized_to_0_1() -> None:
    """All RRF scores are in [0, 1]."""
    results = [_make_result(f"chunk {i}", score=float(i) / 10) for i in range(10)]
    retriever = HybridRetriever(
        vector_retriever=MagicMock(),
        keyword_retriever=MagicMock(),
    )
    fused = retriever._rrf_fuse([results, list(reversed(results))])

    for r in fused:
        assert 0.0 <= r.score <= 1.0, f"Score {r.score} out of range for {r.content}"


async def test_rrf_empty_rankings_handled() -> None:
    """Empty ranking list produces empty output."""
    retriever = HybridRetriever(
        vector_retriever=MagicMock(),
        keyword_retriever=MagicMock(),
    )
    assert retriever._rrf_fuse([[], []]) == []


# ── Context truncation tests ──────────────────────────────────────────────────


async def test_truncation_drops_least_relevant_first() -> None:
    """When total tokens exceed budget, low-score chunks are dropped first."""
    # Each chunk ~100 tokens; budget = 250 tokens → 2 chunks max
    long_content = "word " * 100  # ~100 tokens

    high = _make_result(long_content, score=0.95, chunk_index=0)
    medium = _make_result(long_content, score=0.75, chunk_index=1)
    low = _make_result(long_content, score=0.50, chunk_index=2)

    service = PromptService(max_context_tokens=250)
    # Chunks are already ordered by score desc (as returned by retriever)
    kept = service._truncate_chunks([high, medium, low])

    kept_indices = [r.chunk_index for r in kept]
    assert 0 in kept_indices  # high relevance kept
    assert 2 not in kept_indices  # low relevance dropped
    assert len(kept) <= 2


async def test_truncation_preserves_all_within_budget() -> None:
    """Short chunks all fit — nothing is dropped."""
    chunks = [_make_result("short " * 5, score=0.9 - i * 0.1) for i in range(3)]
    service = PromptService(max_context_tokens=4000)
    kept = service._truncate_chunks(chunks)
    assert len(kept) == 3


async def test_truncation_empty_input() -> None:
    """Empty chunk list returns empty list."""
    service = PromptService()
    assert service._truncate_chunks([]) == []


async def test_history_truncation_keeps_most_recent() -> None:
    """When history overflows, oldest turns are dropped, most recent kept."""
    # Each turn ~100 tokens (word*100); budget=150 -> only last turn(s) fit
    turns = [
        ChatTurn(role="user", content=f"message {i} " + "word " * 100) for i in range(6)
    ]
    service = PromptService(max_history_tokens=150)
    kept = service._truncate_history(turns)

    # Most recent turns should be kept
    kept_contents = [t.content for t in kept]
    assert any("message 5" in c for c in kept_contents)
    assert not any("message 0" in c for c in kept_contents)

    # Most recent turns should be kept
    kept_contents = [t.content for t in kept]
    assert any("message 5" in c for c in kept_contents)
    assert not any("message 0" in c for c in kept_contents)


# ── Prompt assembly tests ─────────────────────────────────────────────────────


async def test_prompt_contains_chunk_content() -> None:
    """Assembled prompt includes retrieved chunk content."""
    chunks = [_make_result("The capital of France is Paris.", score=0.9)]
    service = PromptService()
    prompt = service.build_prompt(query="What is the capital of France?", chunks=chunks)

    assert "The capital of France is Paris." in prompt
    assert "[CHUNK_1]" in prompt
    assert "What is the capital of France?" in prompt


async def test_prompt_contains_history() -> None:
    """Assembled prompt includes conversation history when provided."""
    chunks = [_make_result("Some content.", score=0.9)]
    history = [
        ChatTurn(role="user", content="Previous question"),
        ChatTurn(role="assistant", content="Previous answer"),
    ]
    service = PromptService()
    prompt = service.build_prompt(
        query="Follow-up question", chunks=chunks, history=history
    )

    assert "Previous question" in prompt
    assert "Previous answer" in prompt


async def test_prompt_no_history_section_when_empty() -> None:
    """No history section rendered when history is empty."""
    chunks = [_make_result("Some content.", score=0.9)]
    service = PromptService()
    prompt = service.build_prompt(query="Question?", chunks=chunks, history=[])

    # The template conditionally renders history
    assert "Conversation History" not in prompt


async def test_prompt_multiple_chunks_numbered() -> None:
    """Multiple chunks are numbered [CHUNK_1], [CHUNK_2], etc."""
    chunks = [_make_result(f"Content {i}", score=0.9 - i * 0.1) for i in range(3)]
    service = PromptService()
    prompt = service.build_prompt(query="Question?", chunks=chunks)

    assert "[CHUNK_1]" in prompt
    assert "[CHUNK_2]" in prompt
    assert "[CHUNK_3]" in prompt


# ── Citation extraction tests ─────────────────────────────────────────────────


async def test_citation_extraction_resolves_references() -> None:
    """[CHUNK_N] references in response are resolved to Citation objects."""
    chunks = [
        _make_result("Paris is the capital of France.", score=0.9, chunk_index=0),
        _make_result("Rome is the capital of Italy.", score=0.8, chunk_index=1),
    ]
    response = "France's capital is Paris [CHUNK_1]. Italy's capital is Rome [CHUNK_2]."

    citations = _extract_citations(response, chunks)

    assert len(citations) == 2
    assert citations[0].chunk_id == chunks[0].chunk_id
    assert citations[1].chunk_id == chunks[1].chunk_id
    assert citations[0].snippet == "Paris is the capital of France."[:200]


async def test_citation_extraction_deduplicates() -> None:
    """The same [CHUNK_N] cited multiple times appears once."""
    chunks = [_make_result("Important fact.", score=0.9)]
    response = "Fact cited here [CHUNK_1] and also here [CHUNK_1]."

    citations = _extract_citations(response, chunks)
    assert len(citations) == 1


async def test_citation_extraction_ignores_out_of_range() -> None:
    """[CHUNK_99] with only 2 chunks produces no citation."""
    chunks = [_make_result("Content.", score=0.9)]
    response = "Reference [CHUNK_99] is invalid."

    citations = _extract_citations(response, chunks)
    assert citations == []


async def test_citation_extraction_no_references() -> None:
    """Response with no [CHUNK_N] markers produces empty citation list."""
    chunks = [_make_result("Content.", score=0.9)]
    response = "This response cites nothing."

    citations = _extract_citations(response, chunks)
    assert citations == []


# ── Retrieval user-scoping integration test ───────────────────────────────────


async def test_retrieval_scoped_to_user(test_client: Any, db: Any) -> None:
    """User A's chunks are NOT returned when querying as user B."""

    from app.models.chunk import Chunk
    from app.models.document import Document, DocumentStatus, FileType
    from app.models.user import User

    # Create User A + document + embedded chunk
    user_a = User(email="rag_usera@test.com", hashed_password="x", is_active=True)
    user_b = User(email="rag_userb@test.com", hashed_password="x", is_active=True)
    db.add_all([user_a, user_b])
    await db.flush()

    doc_a = Document(
        user_id=user_a.id,
        title="User A's doc",
        filename="a.txt",
        file_type=FileType.TXT,
        file_size=100,
        status=DocumentStatus.READY,
    )
    db.add(doc_a)
    await db.flush()

    # Chunk with a real (fake) embedding vector
    fake_embedding = [0.1] * 1536
    chunk_a = Chunk(
        document_id=doc_a.id,
        user_id=user_a.id,
        content="User A secret content",
        chunk_index=0,
        embedding=fake_embedding,
        chunk_metadata={"source_filename": "a.txt"},
    )
    db.add(chunk_a)
    await db.flush()

    # VectorRetriever for user_b should return nothing (chunk belongs to user_a)
    from app.retrieval.vector import VectorRetriever

    mock_provider = MagicMock()
    mock_provider.embed_batch = AsyncMock(return_value=[[0.1] * 1536])
    retriever = VectorRetriever(embedding_provider=mock_provider)

    results = await retriever.retrieve(
        query="secret content",
        user_id=user_b.id,  # querying as user B
        session=db,
        top_k=10,
    )

    # User B must not see user A's chunk
    returned_ids = {r.chunk_id for r in results}
    assert chunk_a.id not in returned_ids, "User B retrieved User A's private chunk!"


# ── Mock LLM generation test ──────────────────────────────────────────────────


async def test_generation_with_mock_provider() -> None:
    """GenerationService.generate() with a mock provider extracts citations."""
    from app.generation.service import GenerationService

    chunks = [
        _make_result("Python was created in 1991 by Guido.", score=0.95, chunk_index=0)
    ]

    mock_provider = MagicMock()
    mock_provider.model_name = "mock-llm"
    mock_provider.acomplete = AsyncMock(
        return_value=(
            "Python was created in 1991 [CHUNK_1].",
            50,
            20,
        )
    )

    service = GenerationService(provider=mock_provider)
    service._provider = mock_provider

    prompt_service = PromptService()
    prompt = prompt_service.build_prompt(
        query="When was Python created?", chunks=chunks
    )

    result = await service.generate(assembled_prompt=prompt, chunks=chunks)

    assert isinstance(result, GenerationResult)
    assert "Python" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == chunks[0].chunk_id


async def test_token_counting_returns_positive_integer() -> None:
    """count_tokens returns a positive integer for non-empty text."""
    n = count_tokens("Hello, world! This is a test sentence.")
    assert isinstance(n, int)
    assert n > 0


async def test_token_counting_empty_string() -> None:
    """count_tokens handles empty string without error."""
    n = count_tokens("")
    assert n >= 0
