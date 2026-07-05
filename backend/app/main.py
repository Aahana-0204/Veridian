from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import close_db, init_db
from app.core.logging import configure_logging
from app.core.redis import close_redis, init_redis
from app.routers import auth as auth_router
from app.routers import chat as chat_router
from app.routers import documents as documents_router
from app.routers import health as health_router
from app.routers import users as users_router
from app.schemas.common import ErrorResponse

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    init_db(settings.database_url)
    await init_redis(settings.redis_url)
    logger.info(
        "startup",
        app=settings.app_name,
        environment=settings.environment,
        version="0.1.0",
    )
    yield
    await close_db()
    await close_redis()
    logger.info("shutdown")


def create_app() -> FastAPI:
    """Application factory — instantiate with different settings in tests."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(documents_router.router)
    app.include_router(chat_router.router)

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_server_error",
                detail="An unexpected error occurred.",
            ).model_dump(),
        )

    return app


app = create_app()
