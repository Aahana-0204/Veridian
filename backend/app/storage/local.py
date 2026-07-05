"""Local filesystem storage backend.

Files are stored under:
    {base_dir}/{document_id}/{original_filename}

The directory structure keeps each document's file isolated so concurrent
uploads never collide even if filenames are identical.
"""

from __future__ import annotations

from pathlib import Path

import aiofiles
import structlog

from app.storage.base import StorageBackend

logger = structlog.get_logger(__name__)


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, document_id: str, filename: str, data: bytes) -> str:
        doc_dir = self.base_dir / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        path = doc_dir / filename
        async with aiofiles.open(path, "wb") as fh:
            await fh.write(data)
        logger.debug("storage_save", path=str(path), bytes=len(data))
        return str(path)

    async def load(self, path: str) -> bytes:
        async with aiofiles.open(path, "rb") as fh:
            return await fh.read()

    async def delete(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()
            logger.debug("storage_delete", path=str(p))
        # Best-effort: remove the now-empty document directory
        import contextlib

        with contextlib.suppress(OSError):
            p.parent.rmdir()

    async def exists(self, path: str) -> bool:
        return Path(path).exists()
