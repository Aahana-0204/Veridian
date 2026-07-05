#!/usr/bin/env python
"""Standalone script: verify that all chunks for a document have embeddings.

Usage
-----
::

    # From the /backend directory (with the .env loaded):
    python scripts/verify_embeddings.py <document_id>

    # Or via Docker:
    docker compose exec backend python scripts/verify_embeddings.py <document_id>

Exit codes
----------
0 — All chunks have embeddings (complete=true).
1 — One or more chunks are missing embeddings.
2 — Document not found, or usage error.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import structlog

logger = structlog.get_logger(__name__)


async def _verify(document_id: uuid.UUID) -> int:
    """Query the database and print a verification report.  Returns an exit code."""
    import os
    import sys

    # Allow running from the repo root or from /backend
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.chunk import Chunk
    from app.models.document import Document

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with session_factory() as session:
        # Fetch document
        doc_result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc is None:
            print(f"ERROR: Document {document_id} not found.", file=sys.stderr)
            await engine.dispose()
            return 2

        # Count total chunks
        total_result = await session.execute(
            select(func.count()).where(Chunk.document_id == document_id)
        )
        total: int = total_result.scalar_one()

        # Count chunks with non-null embeddings
        with_emb_result = await session.execute(
            select(func.count()).where(
                Chunk.document_id == document_id,
                Chunk.embedding.is_not(None),
            )
        )
        with_embeddings: int = with_emb_result.scalar_one()

    await engine.dispose()

    missing = total - with_embeddings
    complete = missing == 0 and total > 0

    print(f"Document ID : {doc.id}")
    print(f"Title       : {doc.title!r}")
    print(f"Status      : {doc.status.value}")
    print(f"Total chunks: {total}")
    print(f"With embeddings   : {with_embeddings}")
    print(f"Missing embeddings: {missing}")
    print(f"Complete    : {'✅ YES' if complete else '❌ NO'}")

    if doc.error_message:
        print(f"Error       : {doc.error_message}", file=sys.stderr)

    return 0 if complete else 1


def main() -> None:
    if len(sys.argv) != 2:
        print(
            f"Usage: python {sys.argv[0]} <document_id>",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        doc_id = uuid.UUID(sys.argv[1])
    except ValueError:
        print(f"ERROR: '{sys.argv[1]}' is not a valid UUID.", file=sys.stderr)
        sys.exit(2)

    exit_code = asyncio.run(_verify(doc_id))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
