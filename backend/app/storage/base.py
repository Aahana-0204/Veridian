"""Abstract storage backend interface.

Implementing a new backend (e.g. S3, GCS) only requires subclassing
StorageBackend and registering it as the FastAPI dependency in get_storage().
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Minimal interface for persisting and retrieving raw uploaded files."""

    @abstractmethod
    async def save(self, document_id: str, filename: str, data: bytes) -> str:
        """Persist *data* and return the opaque storage path/key.

        The returned path is stored on the Document row and passed back to
        :meth:`load` / :meth:`delete`.
        """

    @abstractmethod
    async def load(self, path: str) -> bytes:
        """Return the raw bytes previously saved at *path*."""

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Permanently remove the file at *path* (idempotent — no error if missing)."""

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Return True if a file exists at *path*."""
