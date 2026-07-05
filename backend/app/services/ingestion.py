"""Document ingestion pipeline.

Responsibilities
----------------
1. Compute SHA-256 content hash for deduplication.
2. Parse the raw file into text via ``unstructured``.
3. Split text into overlapping chunks via LangChain RecursiveCharacterTextSplitter.
4. Persist chunk rows in the database.
5. Generate embeddings for each chunk via ``EmbeddingService``.
6. Update document status (queued -> processing -> ready | failed).

This module is intentionally free of FastAPI concerns so it can be tested
independently and migrated to Celery/RQ in the future.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

import structlog
from langchain_text_splitters.character import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus

logger = structlog.get_logger(__name__)


# -- Helpers ------------------------------------------------------------------


def compute_content_hash(data: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    """Split *text* into overlapping chunks using a recursive character splitter.

    Falls back to settings values when chunk_size / chunk_overlap are not given.
    This function is pure (no I/O) so it is straightforward to unit-test.
    """
    if chunk_size is None or chunk_overlap is None:
        settings = get_settings()
        chunk_size = chunk_size if chunk_size is not None else settings.chunk_size
        chunk_overlap = (
            chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
        )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def _extract_text(file_path: Path) -> tuple[str, list[int | None]]:
    """Parse *file_path* with unstructured and return (full_text, page_numbers).

    Returns a flat string of all extracted text and a parallel list mapping each
    unstructured Element to its page number (None if unavailable / not a PDF).
    Isolates the unstructured import so the rest of the module stays testable
    without the heavy optional dependencies installed.
    """
    from unstructured.partition.auto import partition  # heavy optional dep

    elements = partition(filename=str(file_path))
    texts: list[str] = []
    pages: list[int | None] = []

    for elem in elements:
        raw = elem.text if hasattr(elem, "text") else str(elem)
        if not raw or not raw.strip():
            continue
        texts.append(raw.strip())
        page = (
            getattr(elem.metadata, "page_number", None)
            if hasattr(elem, "metadata")
            else None
        )
        pages.append(page)

    return "\n\n".join(texts), pages


def _assign_page_numbers(
    chunks: list[str], elements_text: str, element_pages: list[int | None]
) -> list[int | None]:
    """Best-effort: find which page each chunk originated from."""
    result: list[int | None] = []
    for chunk in chunks:
        probe = chunk[:100]
        matched_page: int | None = None
        for elem_text, page in zip(
            elements_text.split("\n\n"), element_pages, strict=False
        ):
            if probe in elem_text:
                matched_page = page
                break
        result.append(matched_page)
    return result


# -- Main pipeline ------------------------------------------------------------


async def process_document(document_id: uuid.UUID, file_path: str) -> None:
    """Entry point for the background task.

    Opens its own database session -- the FastAPI request session is already
    closed by the time background tasks run.  Constructs the EmbeddingService
    from settings so the pipeline is fully self-contained.
    """
    from app.embeddings import EmbeddingProviderFactory
    from app.embeddings.retry import RetryPolicy
    from app.services.embedding_service import EmbeddingService

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    # Build embedding service -- fail early if misconfigured
    embedding_service: EmbeddingService | None = None
    try:
        provider = EmbeddingProviderFactory.create(settings)
        retry_policy = RetryPolicy(
            max_attempts=settings.embedding_max_retries,
            base_delay=settings.embedding_retry_base_delay,
            max_delay=settings.embedding_retry_max_delay,
        )
        embedding_service = EmbeddingService(
            provider=provider,
            retry_policy=retry_policy,
            max_concurrency=settings.embedding_max_concurrency,
        )
    except Exception as exc:
        logger.error(
            "embedding_service_init_failed",
            document_id=str(document_id),
            error=str(exc),
        )

    try:
        async with factory() as session:
            await _run_pipeline(
                session,
                document_id,
                Path(file_path),
                embedding_service=embedding_service,
            )
    finally:
        await engine.dispose()


async def _run_pipeline(
    session: AsyncSession,
    document_id: uuid.UUID,
    file_path: Path,
    embedding_service: object | None = None,
) -> None:
    """Core pipeline -- separated so tests can inject a session and service.

    Parameters
    ----------
    session:
        Active AsyncSession (test sessions or a fresh background session).
    document_id:
        UUID of the Document row to process.
    file_path:
        Absolute path to the stored raw file.
    embedding_service:
        Optional EmbeddingService.  When None, the document is marked FAILED
        with a clear message so the operator knows embeddings are missing.
    """
    from app.services.embedding_service import EmbeddingService

    result = await session.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        logger.error("ingestion_document_not_found", document_id=str(document_id))
        return

    logger.info("ingestion_start", document_id=str(document_id), path=str(file_path))

    doc.status = DocumentStatus.PROCESSING
    await session.commit()

    try:
        # 1. Parse
        full_text, element_pages = _extract_text(file_path)
        if not full_text.strip():
            raise ValueError("Parsed document produced no text content.")

        # 2. Chunk
        settings = get_settings()
        raw_chunks = chunk_text(full_text, settings.chunk_size, settings.chunk_overlap)
        page_assignments = _assign_page_numbers(raw_chunks, full_text, element_pages)

        # 3. Persist chunk rows (embedding=NULL initially)
        chunk_rows: list[Chunk] = []
        for idx, (text, page) in enumerate(
            zip(raw_chunks, page_assignments, strict=False)
        ):
            token_est = len(text.split())
            meta: dict[str, Any] = {
                "source_filename": doc.filename,
                "file_type": doc.file_type.value,
            }
            if page is not None:
                meta["page_number"] = page
            chunk_rows.append(
                Chunk(
                    document_id=doc.id,
                    user_id=doc.user_id,
                    content=text,
                    chunk_index=idx,
                    page_number=page,
                    token_count=token_est,
                    chunk_metadata=meta,
                )
            )

        session.add_all(chunk_rows)
        await session.flush()

        # 4. Generate embeddings
        if embedding_service is None:
            raise ValueError(
                "EmbeddingService is not available (provider misconfigured or "
                "OPENAI_API_KEY missing). Chunks stored without embeddings."
            )

        typed_service: EmbeddingService = embedding_service  # type: ignore[assignment]
        await typed_service.embed_chunks(chunk_rows, session)

        # 5. Finalise
        doc.status = DocumentStatus.READY
        doc.chunk_count = len(chunk_rows)
        doc.error_message = None
        await session.commit()
        logger.info(
            "ingestion_complete",
            document_id=str(document_id),
            chunks=len(chunk_rows),
        )

    except Exception as exc:
        await session.rollback()
        result2 = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        doc2 = result2.scalar_one_or_none()
        if doc2:
            doc2.status = DocumentStatus.FAILED
            doc2.error_message = f"{type(exc).__name__}: {exc}"[:500]
            await session.commit()
        logger.error(
            "ingestion_failed",
            document_id=str(document_id),
            error=str(exc),
            exc_info=exc,
        )
