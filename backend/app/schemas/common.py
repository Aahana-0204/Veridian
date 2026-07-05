"""Shared response schemas used across all routers."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx / 5xx responses."""

    error: str
    detail: str | None = None
    code: str | None = None


class PaginationMeta(BaseModel):
    """Pagination metadata included in every paginated list response."""

    total: int
    page: int
    size: int
    pages: int
