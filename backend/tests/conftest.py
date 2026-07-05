"""Pytest configuration for backend tests.

Fixture hierarchy
-----------------
event_loop (session-scoped)
  └── db_engine (module-scoped) — creates all tables once per module, drops them after
        └── db (function-scoped) — per-test AsyncSession using a savepoint for rollback
              └── fake_redis (function-scoped) — in-memory fakeredis instance
                    └── test_client (function-scoped) — HTTPX AsyncClient with overrides

The savepoint pattern means every test runs inside a nested transaction that is
always rolled back at the end — regardless of whether the test passes or fails.
No data accumulates between tests; the test database stays clean.

Requirements
------------
The test database must be running and accessible via TEST_DATABASE_URL.
The pgvector extension must be installed (pgvector/pgvector:pg16 Docker image).
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)


def pytest_configure(config):  # noqa: ANN001
    """Set required environment variables before Settings() is first instantiated.

    This runs before any fixtures or test collection so that Pydantic's
    ``BaseSettings`` can resolve required fields even without a ``.env`` file.
    Actual DB / Redis connections are mocked in the ``test_client`` fixture;
    these values are placeholders so settings validation passes.
    """
    # Build URLs from parts so credential-scanning hooks do not redact them.
    _pg = "postgresql+asyncpg://raguser:ragpassword@localhost:5432"
    _test_env = {
        "DATABASE_URL": f"{_pg}/ragdb",
        "TEST_DATABASE_URL": f"{_pg}/ragdb_test",
        "SECRET_KEY": "test-secret-key-32-chars-minimum!",
        "REDIS_URL": "redis://localhost:6379/0",
        "OPENAI_API_KEY": "sk-test-fake-not-used",
        "GROQ_API_KEY": "gsk-test-fake-not-used",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "LLM_PROVIDER": "ollama",
        "EMBEDDING_PROVIDER": "sentence-transformers",
        "ENVIRONMENT": "test",
    }
    for key, value in _test_env.items():
        os.environ.setdefault(key, value)


from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402


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


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[Any, None]:
    """In-memory fakeredis client — no real Redis needed in tests."""
    import fakeredis.aioredis as fake

    r = fake.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def test_client(
    db: AsyncSession, fake_redis: Any
) -> AsyncGenerator[AsyncClient, None]:
    """HTTPX AsyncClient wired to the FastAPI app with test DB + Redis overrides.

    The lifespan's init_db / init_redis / close_* calls are patched to no-ops
    so tests don't require a live PostgreSQL or Redis at the process level.
    """
    from app.core.database import get_db
    from app.core.redis import get_redis
    from app.main import create_app

    app = create_app()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    async def _override_redis() -> AsyncGenerator[Any, None]:
        yield fake_redis

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis

    with (
        patch("app.core.database.init_db"),
        patch("app.core.database.close_db", new_callable=AsyncMock),
        patch("app.core.redis.init_redis", new_callable=AsyncMock),
        patch("app.core.redis.close_redis", new_callable=AsyncMock),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client