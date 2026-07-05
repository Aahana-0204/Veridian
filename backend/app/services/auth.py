"""Authentication helpers: password hashing, JWT creation/verification, Redis token store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, status

from app.core.config import get_settings

logger = structlog.get_logger(__name__)
_ph = PasswordHasher()


# ── Password ──────────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return an argon2id hash of *plain*."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*, False on mismatch."""
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────


def _encode(payload: dict[str, Any], expires_at: datetime) -> str:
    settings = get_settings()
    return jwt.encode(
        {**payload, "exp": expires_at, "iat": datetime.now(tz=UTC)},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def create_access_token(user_id: uuid.UUID) -> str:
    """Return a short-lived JWT access token."""
    settings = get_settings()
    expire = datetime.now(tz=UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return _encode({"sub": str(user_id), "type": "access"}, expire)


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str]:
    """Return ``(encoded_jwt, jti)``. The jti is the Redis key fragment."""
    jti = str(uuid.uuid4())
    settings = get_settings()
    expire = datetime.now(tz=UTC) + timedelta(days=settings.refresh_token_expire_days)
    token = _encode({"sub": str(user_id), "type": "refresh", "jti": jti}, expire)
    return token, jti


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises HTTP 401 on any failure."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err
    except jwt.InvalidTokenError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err


# ── Redis refresh-token store ─────────────────────────────────────────────────


def _redis_key(user_id: str, jti: str) -> str:
    return f"refresh:{user_id}:{jti}"


async def store_refresh_token(redis: Any, user_id: str, jti: str) -> None:
    """Write refresh token to Redis with the configured TTL."""
    ttl = get_settings().refresh_token_expire_days * 86_400
    await redis.setex(_redis_key(user_id, jti), ttl, "1")


async def revoke_refresh_token(redis: Any, user_id: str, jti: str) -> None:
    """Delete a refresh token from Redis (logout / token rotation)."""
    await redis.delete(_redis_key(user_id, jti))


async def is_refresh_token_valid(redis: Any, user_id: str, jti: str) -> bool:
    """Return True if the token still exists in Redis (not revoked)."""
    return bool(await redis.exists(_redis_key(user_id, jti)))
