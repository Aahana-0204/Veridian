"""Storage package — backend abstraction for raw file I/O."""

from app.storage.base import StorageBackend
from app.storage.local import LocalStorageBackend

__all__ = ["StorageBackend", "LocalStorageBackend"]
