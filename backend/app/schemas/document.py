import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.document import DocumentStatus, FileType


class DocumentBase(BaseModel):
    title: str
    filename: str
    file_type: FileType
    file_size: int

    @field_validator("file_size")
    @classmethod
    def file_size_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("file_size must be positive.")
        return v


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    title: str | None = None
    status: DocumentStatus | None = None
    chunk_count: int | None = None
    error_message: str | None = None


class DocumentResponse(DocumentBase):
    id: uuid.UUID
    user_id: uuid.UUID
    status: DocumentStatus
    chunk_count: int
    error_message: str | None = None
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    status: DocumentStatus
    chunk_count: int
    error_message: str | None = None

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    size: int
    pages: int
