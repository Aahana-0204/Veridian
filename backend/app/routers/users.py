"""User profile endpoints (all protected)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_active_user
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse, summary="Get current user profile")
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> User:
    return current_user


@router.patch("/me", response_model=UserResponse, summary="Update current user profile")
async def update_me(
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> User:
    if body.full_name is not None:
        current_user.full_name = body.full_name
    # is_active changes are admin-only; silently ignored here
    await db.commit()
    await db.refresh(current_user)
    logger.info("user_profile_updated", user_id=str(current_user.id))
    return current_user
