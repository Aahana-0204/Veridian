import structlog
from fastapi import APIRouter

from app.core.database import check_db_connection
from app.schemas.health import HealthResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns API status and database connectivity.",
)
async def health_check() -> HealthResponse:
    db_ok = await check_db_connection()
    status = "ok" if db_ok else "degraded"

    logger.info("health_check", status=status, database_ok=db_ok)

    return HealthResponse(
        status=status,
        database="connected" if db_ok else "disconnected",
        version="0.1.0",
    )
