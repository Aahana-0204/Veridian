"""Alembic environment for async SQLAlchemy (asyncpg driver).

Database URL is read from the DATABASE_URL environment variable,
falling back to alembic.ini's sqlalchemy.url for offline mode.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Alembic Config ──────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Override URL from environment ───────────────────────────────────────────
# Alembic requires a *sync* URL; strip the +asyncpg dialect qualifier.
_raw_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
_sync_url = _raw_url.replace("postgresql+asyncpg://", "postgresql://")
config.set_main_option("sqlalchemy.url", _sync_url)

# target_metadata will be set to Base.metadata in Part 2 when models exist.
target_metadata = None


# ── Offline mode (no live DB connection) ────────────────────────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (async connection) ──────────────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Re-use the async URL for the engine (put +asyncpg back)
    async_url = _raw_url if _raw_url.startswith("postgresql+asyncpg") else _raw_url
    cfg_section = config.get_section(config.config_ini_section, {})
    cfg_section["sqlalchemy.url"] = async_url

    connectable = async_engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
