"""Document management endpoints (upload, list, status, delete)."""

from __future__ import annotations

import math
import uuid

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus, FileType
from app.models.user import User
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
    EmbeddingVerificationResponse,
)
from app.services.ingestion import compute_content_hash, process_document
from app.storage.base import StorageBackend
from app.storage.deps import get_storage

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

# Allowed MIME types → FileType enum
_MIME_TO_FILE_TYPE: dict[str, FileType] = {
    "application/pdf": FileType.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.DOCX,
    "text/plain": FileType.TXT,
    "text/markdown": FileType.MD,
    "text/html": FileType.HTML,
    "text/x-markdown": FileType.MD,
}
_EXT_TO_FILE_TYPE: dict[str, FileType] = {
    ".pdf": FileType.PDF,
    ".docx": FileType.DOCX,
    ".txt": FileType.TXT,
    ".md": FileType.MD,
    ".html": FileType.HTML,
    ".htm": FileType.HTML,
}


def _resolve_file_type(filename: str, content_type: str | None) -> FileType:
    """Determine FileType from content-type header or file extension."""
    if content_type and content_type in _MIME_TO_FILE_TYPE:
        return _MIME_TO_FILE_TYPE[content_type]
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _EXT_TO_FILE_TYPE:
        return _EXT_TO_FILE_TYPE[ext]
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"Unsupported file type '{ext or content_type}'. "
        "Allowed: pdf, docx, txt, md, html.",
    )


# ── Upload ────────────────────────────────────────────────────────────────────


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for ingestion",
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    current_user: User = Depends(get_current_active_user),
) -> DocumentResponse:
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    file_type = _resolve_file_type(file.filename or "", file.content_type)

    # Read with size guard — avoid buffering huge files
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_size_mb} MB limit.",
        )

    content_hash = compute_content_hash(data)
    safe_filename = file.filename or f"upload_{uuid.uuid4().hex}"

    # Dedup: same user, same file content → return existing document
    existing = await db.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.content_hash == content_hash,
        )
    )
    if dup := existing.scalar_one_or_none():
        logger.info(
            "upload_duplicate_skipped",
            document_id=str(dup.id),
            content_hash=content_hash,
        )
        return DocumentResponse.model_validate(dup)

    doc = Document(
        user_id=current_user.id,
        title=title or safe_filename,
        filename=safe_filename,
        file_type=file_type,
        file_size=len(data),
        status=DocumentStatus.QUEUED,
        content_hash=content_hash,
    )
    db.add(doc)
    await db.flush()  # get doc.id before committing

    storage_path = await storage.save(str(doc.id), safe_filename, data)
    doc.storage_path = storage_path
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(process_document, doc.id, storage_path)
    logger.info(
        "upload_accepted",
        document_id=str(doc.id),
        filename=safe_filename,
        bytes=len(data),
    )
    return DocumentResponse.model_validate(doc)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List all documents for the current user (paginated)",
)
async def list_documents(
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DocumentListResponse:
    if page < 1:
        page = 1
    if size < 1 or size > 100:
        size = 20

    base_q = select(Document).where(Document.user_id == current_user.id)
    total_result = await db.execute(select(func.count()).select_from(base_q.subquery()))
    total: int = total_result.scalar_one()

    rows_result = await db.execute(
        base_q.order_by(Document.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    docs = rows_result.scalars().all()

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)),
    )


# ── Status ────────────────────────────────────────────────────────────────────


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Get processing status of a document",
)
async def get_document_status(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DocumentStatusResponse:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )
    return DocumentStatusResponse.model_validate(doc)


# ── Delete ────────────────────────────────────────────────────────────────────


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its chunks",
)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    current_user: User = Depends(get_current_active_user),
) -> None:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )

    storage_path = doc.storage_path
    await db.delete(doc)
    await db.commit()

    if storage_path:
        try:
            await storage.delete(storage_path)
        except Exception as exc:
            # File deletion failure is logged but not re-raised —
            # the DB row is already gone so the user's data is protected.
            logger.warning(
                "storage_delete_failed",
                path=storage_path,
                error=str(exc),
            )
    logger.info("document_deleted", document_id=str(document_id))


# ── Embedding verification ────────────────────────────────────────────────────


@router.get(
    "/{document_id}/embeddings/verify",
    response_model=EmbeddingVerificationResponse,
    summary="Verify that all chunks for a document have embeddings",
)
async def verify_embeddings(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EmbeddingVerificationResponse:
    """Return counts of chunks with and without non-null embedding vectors.

    Useful for confirming that the embedding pipeline ran to completion.
    A document is fully embedded when ``complete=true``.
    """
    # Ensure the document belongs to the current user
    doc_result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == current_user.id,
        )
    )
    doc = doc_result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )

    total_result = await db.execute(
        select(func.count()).where(Chunk.document_id == document_id)
    )
    total: int = total_result.scalar_one()

    with_embeddings_result = await db.execute(
        select(func.count()).where(
            Chunk.document_id == document_id,
            Chunk.embedding.is_not(None),
        )
    )
    with_embeddings: int = with_embeddings_result.scalar_one()

    missing = total - with_embeddings
    logger.info(
        "embedding_verify",
        document_id=str(document_id),
        total=total,
        with_embeddings=with_embeddings,
        missing=missing,
    )
    return EmbeddingVerificationResponse(
        document_id=document_id,
        status=doc.status,
        total_chunks=total,
        chunks_with_embeddings=with_embeddings,
        chunks_missing_embeddings=missing,
        complete=(missing == 0 and total > 0),
    )
