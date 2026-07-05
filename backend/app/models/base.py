from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base — all ORM models inherit from this."""

    pass


class TimestampMixin:
    """Adds created_at / updated_at to any model.

    updated_at is refreshed automatically by SQLAlchemy on every ORM-level UPDATE.
    Direct SQL updates bypass this; add a DB trigger if that becomes a concern.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
