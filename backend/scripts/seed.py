#!/usr/bin/env python3
"""Seed the database with a test user for manual testing.

Usage (from the project root, with .env present):
    python backend/scripts/seed.py

The script is idempotent — running it a second time is a no-op.

Test credentials:
    email:    test@veridian.dev
    password: testpassword123
"""

import asyncio
import sys
from pathlib import Path

# Ensure the backend package is on sys.path regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.models import User

logger = structlog.get_logger(__name__)


async def seed() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_async_engine(settings.database_url, echo=False)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, expire_on_commit=False
    )

    async with factory() as session:
        result = await session.execute(
            select(User).where(User.email == "test@veridian.dev")
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            logger.info(
                "seed_skipped", reason="test user already exists", id=str(existing.id)
            )
            return

        ph = PasswordHasher()
        user = User(
            email="test@veridian.dev",
            hashed_password=ph.hash("testpassword123"),
            full_name="Test User",
            is_active=True,
            is_superuser=False,
        )
        session.add(user)
        await session.commit()
        logger.info("seed_user_created", email=user.email, id=str(user.id))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
