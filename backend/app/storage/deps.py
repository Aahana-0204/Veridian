"""FastAPI dependency that provides the active StorageBackend.

Swap LocalStorageBackend for S3StorageBackend here when needed — no router
code changes required.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageBackend
from app.storage.local import LocalStorageBackend


@lru_cache(maxsize=1)
def _get_storage_backend() -> StorageBackend:
    return LocalStorageBackend(get_settings().upload_dir)


def get_storage() -> StorageBackend:
    """FastAPI dependency — returns the process-wide storage backend singleton."""
    return _get_storage_backend()
