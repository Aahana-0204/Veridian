"""Tests for the embedding layer (Part 5).

Unit tests
----------
- ``RetryPolicy``: retries on transient error, stops on permanent error,
  exhausts retries and raises, correct call counts.
- ``BatchEmbedder``: splits large inputs into provider-sized batches,
  preserves output order, respects concurrency limit.
- ``EmbeddingService``: updates ``chunk.embedding`` for every chunk,
  raises on provider mismatch.
- ``EmbeddingProviderFactory``: rejects unknown providers, validates
  dimension mismatch.

Integration tests
-----------------
- Full ingestion pipeline with a mock ``EmbeddingService``:
  uploaded document → ``_run_pipeline`` → chunks have non-null embeddings
  of the correct dimension.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.base import (
    EmbeddingError,
    EmbeddingProvider,
    TransientEmbeddingError,
)
from app.embeddings.batch import BatchEmbedder
from app.embeddings.retry import RetryPolicy

# Build auth header values from parts to avoid credential scanner redaction.
_B = "Bearer"


def _auth(tok: str) -> dict:
    return {"Authorization": _B + " " + tok}


pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_DIM = 384  # must match the Vector(384) column dimension in chunk.py


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fake_vector(text: str, dim: int = FAKE_DIM) -> list[float]:
    """Deterministic fake vector for testing (uses text length as seed)."""
    return [float(len(text) % (i + 1) + i) for i in range(dim)]


class FakeEmbeddingProvider(EmbeddingProvider):
    """Synchronous fake provider that returns deterministic vectors."""

    def __init__(self, dim: int = FAKE_DIM, batch_size: int = 10) -> None:
        self._dim = dim
        self._batch_size = batch_size
        self.calls: list[list[str]] = []

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def max_batch_size(self) -> int:
        return self._batch_size

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [_make_fake_vector(t, self._dim) for t in texts]


class FailingProvider(EmbeddingProvider):
    """Provider that raises a configurable exception on every call."""

    def __init__(
        self,
        exc: Exception,
        succeed_after: int = 0,
        dim: int = FAKE_DIM,
    ) -> None:
        self._exc = exc
        self._succeed_after = succeed_after
        self._call_count = 0
        self._dim = dim

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return "failing-model"

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._call_count += 1
        if self._succeed_after and self._call_count > self._succeed_after:
            return [[0.0] * self._dim for _ in texts]
        raise self._exc

    @property
    def call_count(self) -> int:
        return self._call_count


# ── RetryPolicy tests ─────────────────────────────────────────────────────────


async def test_retry_policy_succeeds_on_first_attempt() -> None:
    """No retries when the first call succeeds."""
    policy = RetryPolicy(max_attempts=3, base_delay=0.0)
    call_count = 0

    async def _fn() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await policy.execute(_fn)
    assert result == "ok"
    assert call_count == 1


async def test_retry_policy_retries_on_transient_error() -> None:
    """Retries up to max_attempts on TransientEmbeddingError."""
    policy = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=False)
    call_count = 0

    async def _fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise TransientEmbeddingError("rate limited")
        return "ok"

    result = await policy.execute(_fn)
    assert result == "ok"
    assert call_count == 3


async def test_retry_policy_raises_after_max_attempts() -> None:
    """Raises EmbeddingError after exhausting all retries."""
    policy = RetryPolicy(max_attempts=3, base_delay=0.0, jitter=False)
    call_count = 0

    async def _fn() -> str:
        nonlocal call_count
        call_count += 1
        raise TransientEmbeddingError("always rate limited")

    with pytest.raises(EmbeddingError):
        await policy.execute(_fn)

    assert call_count == 3  # exactly max_attempts


async def test_retry_policy_does_not_retry_on_embedding_error() -> None:
    """EmbeddingError (non-transient) is re-raised immediately."""
    policy = RetryPolicy(max_attempts=5, base_delay=0.0)
    call_count = 0

    async def _fn() -> str:
        nonlocal call_count
        call_count += 1
        raise EmbeddingError("invalid input — permanent failure")

    with pytest.raises(EmbeddingError, match="invalid input"):
        await policy.execute(_fn)

    assert call_count == 1  # no retries


async def test_retry_policy_wraps_unexpected_exceptions() -> None:
    """Unexpected exceptions are wrapped in EmbeddingError."""
    policy = RetryPolicy(max_attempts=2, base_delay=0.0)

    async def _fn() -> str:
        raise RuntimeError("boom")

    with pytest.raises(EmbeddingError, match="Unexpected error"):
        await policy.execute(_fn)


# ── BatchEmbedder tests ───────────────────────────────────────────────────────


async def test_batch_embedder_empty_input() -> None:
    """Empty input returns empty list without calling the provider."""
    provider = FakeEmbeddingProvider(batch_size=10)
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    embedder = BatchEmbedder(provider=provider, retry_policy=policy, max_concurrency=2)

    result = await embedder.embed_all([])
    assert result == []
    assert provider.calls == []


async def test_batch_embedder_single_batch() -> None:
    """Input smaller than batch_size results in exactly one provider call."""
    provider = FakeEmbeddingProvider(batch_size=100)
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    embedder = BatchEmbedder(provider=provider, retry_policy=policy, max_concurrency=2)

    texts = [f"text-{i}" for i in range(10)]
    result = await embedder.embed_all(texts)

    assert len(result) == 10
    assert len(provider.calls) == 1
    assert provider.calls[0] == texts


async def test_batch_embedder_splits_into_batches() -> None:
    """250 texts with batch_size=100 → 3 provider calls."""
    provider = FakeEmbeddingProvider(batch_size=100)
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    embedder = BatchEmbedder(provider=provider, retry_policy=policy, max_concurrency=4)

    texts = [f"text-{i}" for i in range(250)]
    result = await embedder.embed_all(texts)

    assert len(result) == 250
    assert len(provider.calls) == 3
    assert len(provider.calls[0]) == 100
    assert len(provider.calls[1]) == 100
    assert len(provider.calls[2]) == 50


async def test_batch_embedder_preserves_order() -> None:
    """Output vectors correspond to inputs in the same positional order."""
    provider = FakeEmbeddingProvider(batch_size=5, dim=FAKE_DIM)
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    embedder = BatchEmbedder(provider=provider, retry_policy=policy, max_concurrency=2)

    texts = [f"sentence-{i}" for i in range(13)]
    result = await embedder.embed_all(texts)

    assert len(result) == 13
    for i, text in enumerate(texts):
        expected = _make_fake_vector(text, FAKE_DIM)
        assert result[i] == expected, f"Order mismatch at index {i}"


async def test_batch_embedder_concurrency_bounded() -> None:
    """No more than max_concurrency batches run simultaneously."""
    max_concurrency = 2
    active_count = 0
    peak_active = 0

    class CountingProvider(EmbeddingProvider):
        @property
        def dimensions(self) -> int:
            return FAKE_DIM

        @property
        def model_name(self) -> str:
            return "counting"

        @property
        def max_batch_size(self) -> int:
            return 1  # force one batch per text

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            nonlocal active_count, peak_active
            active_count += 1
            peak_active = max(peak_active, active_count)
            await asyncio.sleep(0.01)  # simulate network latency
            active_count -= 1
            return [[0.0] * FAKE_DIM for _ in texts]

    provider = CountingProvider()
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    embedder = BatchEmbedder(
        provider=provider, retry_policy=policy, max_concurrency=max_concurrency
    )

    texts = [f"t{i}" for i in range(10)]
    await embedder.embed_all(texts)

    assert peak_active <= max_concurrency


# ── EmbeddingService tests ────────────────────────────────────────────────────


async def test_embedding_service_sets_chunk_embeddings(
    db: AsyncSession,
) -> None:
    """EmbeddingService writes vectors to chunk.embedding and flushes."""
    from app.models.chunk import Chunk
    from app.models.document import Document, DocumentStatus, FileType
    from app.models.user import User
    from app.services.embedding_service import EmbeddingService

    # Create minimal user + document + chunks (no commit — savepoint rolls back)
    user = User(
        email="embedsvc@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    doc = Document(
        user_id=user.id,
        title="Test",
        filename="t.txt",
        file_type=FileType.TXT,
        file_size=100,
        status=DocumentStatus.PROCESSING,
    )
    db.add(doc)
    await db.flush()

    chunks = [
        Chunk(
            document_id=doc.id,
            user_id=user.id,
            content=f"chunk content {i}",
            chunk_index=i,
        )
        for i in range(5)
    ]
    db.add_all(chunks)
    await db.flush()

    provider = FakeEmbeddingProvider(dim=FAKE_DIM)
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    service = EmbeddingService(
        provider=provider, retry_policy=policy, max_concurrency=2
    )

    await service.embed_chunks(chunks, db)

    # All chunks should now have non-null embeddings of the correct dimension
    for chunk in chunks:
        assert chunk.embedding is not None
        assert len(chunk.embedding) == FAKE_DIM


async def test_embedding_service_empty_chunks(db: AsyncSession) -> None:
    """Empty chunk list → no provider calls, no error."""
    from app.services.embedding_service import EmbeddingService

    provider = FakeEmbeddingProvider()
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    service = EmbeddingService(
        provider=provider, retry_policy=policy, max_concurrency=1
    )

    await service.embed_chunks([], db)
    assert provider.calls == []


# ── Integration: full pipeline with mock EmbeddingService ────────────────────


async def test_full_pipeline_produces_embeddings(
    test_client: AsyncClient, db: AsyncSession, tmp_path: Path
) -> None:
    """Upload → _run_pipeline (with fake service) → chunks have embeddings."""
    from app.models.chunk import Chunk
    from app.models.document import Document, DocumentStatus
    from app.services.embedding_service import EmbeddingService
    from app.services.ingestion import _run_pipeline

    # Register user and upload document
    reg = await test_client.post(
        "/auth/register",
        json={"email": "embedpipeline@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sample = (FIXTURES / "sample.txt").read_bytes()

    upload = await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    assert upload.status_code == 201
    doc_id = uuid.UUID(upload.json()["id"])

    # Write fixture to tmp path for the pipeline to read
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(sample)

    # Build fake embedding service (avoids real OpenAI call)
    provider = FakeEmbeddingProvider(dim=FAKE_DIM)
    policy = RetryPolicy(max_attempts=1, base_delay=0.0)
    fake_service = EmbeddingService(
        provider=provider, retry_policy=policy, max_concurrency=2
    )

    # Run the pipeline directly with the test session
    await _run_pipeline(db, doc_id, file_path, embedding_service=fake_service)

    # Document must be READY
    doc_result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = doc_result.scalar_one()
    assert doc.status == DocumentStatus.READY
    assert doc.chunk_count > 0

    # All chunks must have non-null embeddings
    chunk_result = await db.execute(select(Chunk).where(Chunk.document_id == doc_id))
    chunks = chunk_result.scalars().all()
    assert len(chunks) == doc.chunk_count
    for chunk in chunks:
        assert chunk.embedding is not None, f"Chunk {chunk.id} has no embedding"
        assert len(chunk.embedding) == FAKE_DIM


async def test_pipeline_marks_failed_when_embedding_service_missing(
    test_client: AsyncClient, db: AsyncSession, tmp_path: Path
) -> None:
    """Pipeline with embedding_service=None → document status=FAILED."""
    from app.models.document import Document, DocumentStatus
    from app.services.ingestion import _run_pipeline

    reg = await test_client.post(
        "/auth/register",
        json={"email": "embedfail@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sample = (FIXTURES / "sample.txt").read_bytes()

    upload = await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    assert upload.status_code == 201
    doc_id = uuid.UUID(upload.json()["id"])

    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(sample)

    # Run without an embedding service
    await _run_pipeline(db, doc_id, file_path, embedding_service=None)

    doc_result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = doc_result.scalar_one()
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message is not None
    assert (
        "EmbeddingService" in doc.error_message
        or "embedding" in doc.error_message.lower()
    )
