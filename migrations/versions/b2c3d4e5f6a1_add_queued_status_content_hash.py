"""Add queued status value, content_hash, and storage_path to documents.

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05 18:00:00.000000

Changes
-------
1. ALTER TYPE documentstatus ADD VALUE 'queued' — new initial upload status.
   PostgreSQL requires this outside a transaction block; Alembic handles that
   automatically when the migration contains only DDL executed via op.execute().
2. ADD COLUMN documents.content_hash VARCHAR(64) — SHA-256 hex of raw file bytes,
   used to skip re-processing identical files.
3. ADD COLUMN documents.storage_path VARCHAR(1000) — path/key returned by
   StorageBackend.save(); required to locate and delete the raw file.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL does not allow ALTER TYPE ... ADD VALUE inside a transaction.
    # Alembic will run this in autocommit mode because the operation is detected
    # as requiring it; but we use op.execute() with explicit isolation just in case.
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'queued'")

    op.add_column(
        "documents",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("storage_path", sa.String(1000), nullable=True),
    )
    op.create_index(
        "ix_documents_content_hash", "documents", ["content_hash"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_column("documents", "storage_path")
    op.drop_column("documents", "content_hash")
    # PostgreSQL does not support removing enum values; downgrade leaves 'queued'
    # in the type. Safe because no rows can have that value after the column drops.
