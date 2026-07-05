"""Pytest configuration for backend tests.

Fixture hierarchy
-----------------
event_loop (session-scoped)
  └── db_engine (module-scoped) — creates all tables once per module, drops them after
        └── db (function-scoped) — per-test AsyncSession using a savepoint for rollback

The savepoint pattern means every test runs inside a nested transaction that is
always rolled back at the end — regardless of whether the test passes or fails.
No data accumulates between tests; the test database stays clean.

Requirements
------------
The test database must be running and accessible via TEST_DATABASE_URL.
The pgvector extension must be installed (pgvector/pgvector:pg16 Docker image).
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from app.core.config import get_settings
from app.models import Base


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so module-scoped async fixtures share the same loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create engine, create all tables, yield, drop all tables, dispose."""
    settings = get_settings()
    engine = create_async_engine(
        settings.test_database_url, echo=False, pool_pre_ping=True
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session using a SAVEPOINT so all writes are rolled back after the test."""
    async with db_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()
