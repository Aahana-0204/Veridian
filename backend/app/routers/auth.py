"""Auth endpoints: register, login, token refresh, logout."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import make_rate_limiter
from app.core.redis import get_redis
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    is_refresh_token_valid,
    revoke_refresh_token,
    store_refresh_token,
    verify_password,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Rate-limit: 10 registrations / min per IP, 5 logins / min per IP
_register_limit = make_rate_limiter(max_calls=10, window_seconds=60)
_login_limit = make_rate_limiter(max_calls=5, window_seconds=60)


def _token_response(access: str, refresh: str) -> TokenResponse:
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().access_token_expire_minutes * 60,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    redis: Any = Depends(get_redis),
    _rl: None = Depends(_register_limit),
) -> TokenResponse:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError as err:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from err

    access = create_access_token(user.id)
    refresh, jti = create_refresh_token(user.id)
    await store_refresh_token(redis, str(user.id), jti)

    logger.info("user_registered", user_id=str(user.id))
    return _token_response(access, refresh)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis: Any = Depends(get_redis),
    _rl: None = Depends(_login_limit),
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    access = create_access_token(user.id)
    refresh, jti = create_refresh_token(user.id)
    await store_refresh_token(redis, str(user.id), jti)

    logger.info("user_logged_in", user_id=str(user.id))
    return _token_response(access, refresh)


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Exchange a refresh token for a new access token",
)
async def refresh_token(
    body: RefreshRequest,
    redis: Any = Depends(get_redis),
) -> AccessTokenResponse:
    payload = decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )

    user_id: str = payload.get("sub", "")
    jti: str = payload.get("jti", "")

    if not await is_refresh_token_valid(redis, user_id, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked or does not exist.",
        )

    access = create_access_token(uuid.UUID(user_id))
    logger.info("token_refreshed", user_id=user_id)

    return AccessTokenResponse(
        access_token=access,
        expires_in=get_settings().access_token_expire_minutes * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the refresh token (logout)",
)
async def logout(
    body: RefreshRequest,
    redis: Any = Depends(get_redis),
) -> None:
    try:
        payload = decode_token(body.refresh_token)
        user_id: str = payload.get("sub", "")
        jti: str = payload.get("jti", "")
        await revoke_refresh_token(redis, user_id, jti)
        logger.info("user_logged_out", user_id=user_id)
    except HTTPException:
        # Already-invalid token — logout is idempotent
        pass
