"""Unit tests: model creation, relationships, and cascading deletes.

All tests use the `db` fixture which rolls back every write via SAVEPOINT —
the test database is never permanently modified.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatMessage, ChatSession, MessageRole
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus, FileType
from app.models.user import User

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_user(email: str = "user@example.com") -> User:
    return User(email=email, hashed_password="$argon2id$placeholder", full_name="Test")


def make_document(user_id: uuid.UUID, filename: str = "test.pdf") -> Document:
    return Document(
        user_id=user_id,
        title="Test Document",
        filename=filename,
        file_type=FileType.PDF,
        file_size=1024,
    )


def make_chunk(document_id: uuid.UUID, user_id: uuid.UUID, index: int = 0) -> Chunk:
    return Chunk(
        document_id=document_id,
        user_id=user_id,
        content="Sample chunk content for testing.",
        chunk_index=index,
        page_number=1,
        token_count=8,
    )


# ── User tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_user(db: AsyncSession) -> None:
    user = make_user("create@example.com")
    db.add(user)
    await db.flush()

    assert user.id is not None
    assert user.email == "create@example.com"
    assert user.is_active is True
    assert user.is_superuser is False
    assert user.created_at is not None
    assert user.updated_at is not None


@pytest.mark.asyncio
async def test_user_email_uniqueness(db: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError

    db.add(make_user("dup@example.com"))
    await db.flush()
    db.add(make_user("dup@example.com"))

    with pytest.raises(IntegrityError):
        await db.flush()


# ── Document tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_document(db: AsyncSession) -> None:
    user = make_user("docuser@example.com")
    db.add(user)
    await db.flush()

    doc = make_document(user.id)
    db.add(doc)
    await db.flush()

    assert doc.id is not None
    assert doc.status == DocumentStatus.PENDING
    assert doc.chunk_count == 0
    assert doc.user_id == user.id


@pytest.mark.asyncio
async def test_document_status_default(db: AsyncSession) -> None:
    user = make_user("statustest@example.com")
    db.add(user)
    await db.flush()

    doc = make_document(user.id, "status.pdf")
    db.add(doc)
    await db.flush()

    result = await db.execute(select(Document).where(Document.id == doc.id))
    fetched = result.scalar_one()
    assert fetched.status == DocumentStatus.PENDING


# ── Chunk tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_chunk_without_embedding(db: AsyncSession) -> None:
    user = make_user("chunkuser@example.com")
    db.add(user)
    await db.flush()

    doc = make_document(user.id)
    db.add(doc)
    await db.flush()

    chunk = make_chunk(doc.id, user.id)
    db.add(chunk)
    await db.flush()

    assert chunk.id is not None
    assert chunk.embedding is None  # not embedded yet
    assert chunk.chunk_index == 0


@pytest.mark.asyncio
async def test_chunk_metadata_jsonb(db: AsyncSession) -> None:
    user = make_user("meta@example.com")
    db.add(user)
    await db.flush()

    doc = make_document(user.id)
    db.add(doc)
    await db.flush()

    chunk = Chunk(
        document_id=doc.id,
        user_id=user.id,
        content="Chunk with metadata",
        chunk_index=0,
        chunk_metadata={"section": "Introduction", "heading_level": 1},
    )
    db.add(chunk)
    await db.flush()

    result = await db.execute(select(Chunk).where(Chunk.id == chunk.id))
    fetched = result.scalar_one()
    assert fetched.chunk_metadata == {"section": "Introduction", "heading_level": 1}


# ── Chat tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_chat_session_and_messages(db: AsyncSession) -> None:
    user = make_user("chatuser@example.com")
    db.add(user)
    await db.flush()

    session = ChatSession(user_id=user.id, title="First Session")
    db.add(session)
    await db.flush()

    msg_user = ChatMessage(
        session_id=session.id,
        user_id=user.id,
        role=MessageRole.USER,
        content="What does section 3 say?",
    )
    msg_assistant = ChatMessage(
        session_id=session.id,
        user_id=user.id,
        role=MessageRole.ASSISTANT,
        content="Section 3 discusses...",
        sources={"chunks": [str(uuid.uuid4())]},
        token_count=55,
    )
    db.add_all([msg_user, msg_assistant])
    await db.flush()

    assert msg_user.id is not None
    assert msg_assistant.sources is not None
    assert msg_assistant.token_count == 55


# ── Cascade delete tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cascade_delete_document_removes_chunks(db: AsyncSession) -> None:
    user = make_user("cascade_doc@example.com")
    db.add(user)
    await db.flush()

    doc = make_document(user.id)
    db.add(doc)
    await db.flush()

    chunk = make_chunk(doc.id, user.id)
    db.add(chunk)
    await db.flush()
    chunk_id = chunk.id

    await db.delete(doc)
    await db.flush()

    result = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
    assert (
        result.scalar_one_or_none() is None
    ), "Chunk must be deleted when its parent document is deleted"


@pytest.mark.asyncio
async def test_cascade_delete_user_removes_documents_and_chunks(
    db: AsyncSession,
) -> None:
    user = make_user("cascade_user@example.com")
    db.add(user)
    await db.flush()

    doc = make_document(user.id)
    db.add(doc)
    await db.flush()

    chunk = make_chunk(doc.id, user.id)
    db.add(chunk)
    await db.flush()

    doc_id, chunk_id = doc.id, chunk.id

    await db.delete(user)
    await db.flush()

    doc_row = await db.execute(select(Document).where(Document.id == doc_id))
    assert doc_row.scalar_one_or_none() is None, "Document must be deleted with user"

    chunk_row = await db.execute(select(Chunk).where(Chunk.id == chunk_id))
    assert chunk_row.scalar_one_or_none() is None, "Chunk must be deleted with user"


@pytest.mark.asyncio
async def test_cascade_delete_session_removes_messages(db: AsyncSession) -> None:
    user = make_user("cascade_chat@example.com")
    db.add(user)
    await db.flush()

    session = ChatSession(user_id=user.id)
    db.add(session)
    await db.flush()

    msg = ChatMessage(
        session_id=session.id,
        user_id=user.id,
        role=MessageRole.USER,
        content="Will be removed",
    )
    db.add(msg)
    await db.flush()
    msg_id = msg.id

    await db.delete(session)
    await db.flush()

    result = await db.execute(select(ChatMessage).where(ChatMessage.id == msg_id))
    assert (
        result.scalar_one_or_none() is None
    ), "Message must be deleted when its session is deleted"


# ── Relationship loading tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_documents_relationship(db: AsyncSession) -> None:
    user = make_user("rels@example.com")
    db.add(user)
    await db.flush()

    doc1 = make_document(user.id, "a.pdf")
    doc2 = make_document(user.id, "b.pdf")
    db.add_all([doc1, doc2])
    await db.flush()

    result = await db.execute(
        select(User).options(selectinload(User.documents)).where(User.id == user.id)
    )
    loaded = result.scalar_one()
    assert len(loaded.documents) == 2
    filenames = {d.filename for d in loaded.documents}
    assert filenames == {"a.pdf", "b.pdf"}


@pytest.mark.asyncio
async def test_document_chunks_relationship(db: AsyncSession) -> None:
    user = make_user("chunksrel@example.com")
    db.add(user)
    await db.flush()

    doc = make_document(user.id)
    db.add(doc)
    await db.flush()

    chunks = [make_chunk(doc.id, user.id, i) for i in range(3)]
    db.add_all(chunks)
    await db.flush()

    result = await db.execute(
        select(Document)
        .options(selectinload(Document.chunks))
        .where(Document.id == doc.id)
    )
    loaded = result.scalar_one()
    assert len(loaded.chunks) == 3
    indices = sorted(c.chunk_index for c in loaded.chunks)
    assert indices == [0, 1, 2]
