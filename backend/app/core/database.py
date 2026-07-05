import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


async def check_db_connection() -> bool:
    """Attempt a lightweight SELECT 1 to verify DB reachability."""
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        # Use a minimal pool — we only need this for the health probe
        pool_size=1,
        max_overflow=0,
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("db_connection_failed", error=str(exc))
        return False
    finally:
        await engine.dispose()
