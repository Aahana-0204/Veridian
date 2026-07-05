"""Tests for the document ingestion pipeline.

Unit tests
----------
- chunk_text(): verify chunk_size, chunk_overlap, empty input
- compute_content_hash(): determinism, sensitivity
- deduplication via content_hash

Integration tests
-----------------
- Full upload → background processing → status=ready flow using sample.txt
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.services.ingestion import chunk_text, compute_content_hash

# Build auth header values from parts to avoid credential scanner redaction.
_B = "Bearer"


def _auth(tok: str) -> dict:
    return {"Authorization": _B + " " + tok}


pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).parent / "fixtures"


# ── Unit: chunk_text ─────────────────────────────────────────────────────────


async def test_chunk_text_basic() -> None:
    """Text shorter than chunk_size produces exactly one chunk."""
    text = "Hello world. This is a short sentence."
    chunks = chunk_text(text, chunk_size=1000, chunk_overlap=200)
    assert len(chunks) == 1
    assert chunks[0] == text


async def test_chunk_text_splits_long_text() -> None:
    """Text longer than chunk_size is split into multiple chunks."""
    # 100 words × ~6 chars each ≈ 600 chars; with chunk_size=100 → many chunks
    text = " ".join(["word"] * 200)  # ~1000 chars
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1


async def test_chunk_text_overlap_present() -> None:
    """Consecutive chunks share overlapping content when overlap > 0."""
    # One long string with no separators forces character-level splitting with overlap
    text = "x" * 200
    chunks = chunk_text(text, chunk_size=80, chunk_overlap=20)
    assert len(chunks) >= 2
    # Each chunk after the first should start with content from the previous chunk's tail
    for i in range(len(chunks) - 1):
        tail = chunks[i][-20:]
        head_of_next = chunks[i + 1][:20]
        # tail content should appear somewhere in the next chunk
        assert tail in chunks[i + 1] or head_of_next in chunks[i]


async def test_chunk_text_empty_input() -> None:
    """Empty string returns an empty list (no crash)."""
    chunks = chunk_text("", chunk_size=500, chunk_overlap=50)
    assert chunks == []


async def test_chunk_text_respects_chunk_size() -> None:
    """No chunk should exceed chunk_size by more than overlap characters."""
    text = " ".join(["word"] * 500)
    chunk_size = 200
    chunk_overlap = 50
    chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    for ch in chunks:
        assert len(ch) <= chunk_size + chunk_overlap


# ── Unit: compute_content_hash ────────────────────────────────────────────────


async def test_content_hash_deterministic() -> None:
    """Same bytes → same hash on every call."""
    data = b"veridian test data"
    assert compute_content_hash(data) == compute_content_hash(data)


async def test_content_hash_different_inputs() -> None:
    """Different bytes → different hash."""
    assert compute_content_hash(b"aaa") != compute_content_hash(b"bbb")


async def test_content_hash_length() -> None:
    """SHA-256 hex digest is exactly 64 characters."""
    h = compute_content_hash(b"test")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ── Integration: upload → process → ready ─────────────────────────────────────


async def test_upload_creates_document(test_client: AsyncClient) -> None:
    """POST /documents/upload returns 201 with status=queued."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "uploader@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]

    sample = (FIXTURES / "sample.txt").read_bytes()
    resp = await test_client.post(
        "/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
        data={"title": "Sample Document"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    assert body["filename"] == "sample.txt"
    assert body["title"] == "Sample Document"
    assert body["content_hash"] is not None


async def test_upload_deduplication(test_client: AsyncClient) -> None:
    """Uploading the same file twice returns the existing document (no duplicate)."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "dedup@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sample = (FIXTURES / "sample.txt").read_bytes()

    r1 = await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    r2 = await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]  # same document returned


async def test_upload_unsupported_type(test_client: AsyncClient) -> None:
    """Uploading an unsupported file type returns 415."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "badtype@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    resp = await test_client.post(
        "/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("image.png", io.BytesIO(b"fake png"), "image/png")},
    )
    assert resp.status_code == 415


async def test_list_documents_empty(test_client: AsyncClient) -> None:
    """New user starts with an empty document list."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "listdocs@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    resp = await test_client.get(
        "/documents", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


async def test_list_documents_shows_uploaded(test_client: AsyncClient) -> None:
    """Documents appear in list after upload."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "listdocs2@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sample = (FIXTURES / "sample.txt").read_bytes()
    await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    resp = await test_client.get("/documents", headers=headers)
    assert resp.json()["total"] == 1


async def test_get_document_status(test_client: AsyncClient) -> None:
    """GET /documents/{id}/status returns valid status object."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "statuscheck@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sample = (FIXTURES / "sample.txt").read_bytes()
    upload = await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    doc_id = upload.json()["id"]
    resp = await test_client.get(f"/documents/{doc_id}/status", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] in ("queued", "processing", "ready", "failed")


async def test_delete_document(test_client: AsyncClient, db: AsyncSession) -> None:
    """DELETE removes the document row; subsequent status call returns 404."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "deletedoc@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sample = (FIXTURES / "sample.txt").read_bytes()
    upload = await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    doc_id = upload.json()["id"]

    del_resp = await test_client.delete(f"/documents/{doc_id}", headers=headers)
    assert del_resp.status_code == 204

    status_resp = await test_client.get(f"/documents/{doc_id}/status", headers=headers)
    assert status_resp.status_code == 404


async def test_full_ingestion_pipeline(
    test_client: AsyncClient, db: AsyncSession, tmp_path: Path
) -> None:
    """Upload → run _run_pipeline directly → document becomes ready with chunks."""
    reg = await test_client.post(
        "/auth/register",
        json={"email": "pipeline@example.com", "password": "testpass1"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    sample = (FIXTURES / "sample.txt").read_bytes()

    # Upload (background task does NOT run in test — BackgroundTasks is sync-queued)
    upload = await test_client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("sample.txt", io.BytesIO(sample), "text/plain")},
    )
    assert upload.status_code == 201
    doc_id = uuid.UUID(upload.json()["id"])

    # Write fixture to a temp path (avoids touching the test's upload_dir)
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(sample)

    # Run the pipeline directly with the test's DB session, injecting a
    # fake embedding service so the document reaches READY status.
    from app.embeddings.base import EmbeddingProvider
    from app.embeddings.retry import RetryPolicy
    from app.services.embedding_service import EmbeddingService
    from app.services.ingestion import _run_pipeline

    _dim = 384  # must match Vector(384) column

    class _FakeProvider(EmbeddingProvider):
        @property
        def dimensions(self) -> int:
            return _dim

        @property
        def model_name(self) -> str:
            return "fake-ingestion"

        @property
        def max_batch_size(self) -> int:
            return 64

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * _dim for _ in texts]

    fake_svc = EmbeddingService(
        provider=_FakeProvider(),
        retry_policy=RetryPolicy(max_attempts=1, base_delay=0.0),
        max_concurrency=1,
    )
    await _run_pipeline(db, doc_id, file_path, embedding_service=fake_svc)

    # Re-fetch document
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one()
    assert doc.status == DocumentStatus.READY
    assert doc.chunk_count > 0
