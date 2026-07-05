"""Async database engine, session factory, and FastAPI dependency.

Lifecycle
---------
- ``init_db(url)``  — called once in app lifespan (startup).
- ``close_db()``    — called once in app lifespan (shutdown).
- ``get_db()``      — FastAPI ``Depends`` dependency; one session per request.
- ``check_db_connection()`` — used by /health; runs SELECT 1 via the pool.
"""

from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = structlog.get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str) -> None:
    """Initialise the connection pool and session factory.

    Safe to call multiple times (e.g. in tests) — each call replaces the
    previous engine.
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    # Log host only — never log credentials
    safe_url = database_url.split("@")[-1] if "@" in database_url else database_url
    logger.info("db_initialized", host=safe_url)


async def close_db() -> None:
    """Dispose the connection pool on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        logger.info("db_closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields one AsyncSession per request.

    Commits on clean exit, rolls back on any exception, always closes.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db_connection() -> bool:
    """Probe the live connection pool with SELECT 1.  Used by /health."""
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("db_health_check_failed", error=str(exc))
        return False
