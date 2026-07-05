"""Resize chunks.embedding from Vector(1536) to Vector(384).

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-07-05 23:55:00.000000

Background
----------
The initial schema (Part 2) created ``chunks.embedding`` as ``Vector(1536)``
to match OpenAI ``text-embedding-3-small``.

The default embedding provider is now ``sentence-transformers/all-MiniLM-L6-v2``
which produces **384**-dimensional vectors (free, no API key required).

This migration:
1. Drops the HNSW index on chunks.embedding (cannot ALTER an indexed vector column).
2. Drops and re-adds the column with the new dimension (pgvector does not
   support ALTER COLUMN ... TYPE for vector columns directly; the safest
   approach is drop+add, which is correct since existing vectors are
   dimension-mismatched and must be re-generated anyway).
3. Recreates the HNSW index on the new 384-dim column.

⚠️  Data loss: all existing embedding values are discarded.
    Re-process your documents after running this migration:
    POST /documents/{id}/reprocess  (or re-upload each document).

If you are staying on OpenAI embeddings (1536-dim), do NOT run this
migration.  Set EMBEDDING_DIMENSIONS=1536 and EMBEDDING_PROVIDER=openai
in your .env instead.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_DIM = 384
OLD_DIM = 1536


def upgrade() -> None:
    # 1. Drop the HNSW index so we can alter the column.
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")

    # 2. Drop the old 1536-dim column and add a fresh 384-dim column.
    #    pgvector does not support ALTER COLUMN ... TYPE for vector; drop+add
    #    is the documented approach and is safe because:
    #    a) All existing embeddings must be regenerated (dimension changed).
    #    b) The column is nullable during processing (set to NULL → re-embedded).
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding;")
    op.execute(
        f"ALTER TABLE chunks ADD COLUMN embedding vector({NEW_DIM});"
    )

    # 3. Recreate the HNSW index on the new 384-dim column.
    #    m=16, ef_construction=64 are sensible defaults for this dimension.
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )


def downgrade() -> None:
    # Restore the 1536-dim column (data is lost — embeddings must be regenerated).
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding;")
    op.execute(
        f"ALTER TABLE chunks ADD COLUMN embedding vector({OLD_DIM});"
    )
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )
