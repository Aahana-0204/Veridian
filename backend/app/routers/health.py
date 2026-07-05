import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.health import HealthResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns API status and live database connectivity.",
)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Run SELECT 1 via the shared connection pool to verify DB is reachable."""
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("health_db_check_failed", error=str(exc))
        db_ok = False

    status = "ok" if db_ok else "degraded"
    logger.info("health_check", status=status, database_ok=db_ok)

    return HealthResponse(
        status=status,
        database="connected" if db_ok else "disconnected",
        version="0.1.0",
    )
