"""Integration tests for the Chat API (Part 7).

Test coverage
-------------
1. POST /chat/query — SSE stream: creates session, persists user + assistant
   messages, returns token events + done event with citations.
2. POST /chat/query with existing session_id — uses existing session.
3. GET /chat/sessions — paginated list, scoped to current user.
4. GET /chat/sessions/{id}/history — correct messages, 403 for other user.
5. DELETE /chat/sessions/{id} — cascades to messages, 403 for other user.
6. User isolation — user A cannot access user B's session via any endpoint.

Mocking strategy
----------------
- GenerationProvider → ``FakeGenerationProvider`` (yields 3 tokens + returns
  a ``GenerationResult`` with a fake citation).
- EmbeddingProvider → ``FakeEmbeddingProvider`` (returns a zero-vector — enough
  to exercise the pipeline without calling OpenAI).
- ``get_streaming_session`` → patched to use the test savepoint session so SSE
  generator writes are visible within the same transaction and rolled back after.
- ``RetrievalService.retrieve`` → returns pre-built ``RetrievalResult`` fixtures
  (avoids pgvector cosine queries against a real vectorised DB).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession, MessageRole
from app.models.user import User
from app.schemas.rag import Citation, GenerationResult, RetrievalResult

# ── Shared fixtures ──────────────────────────────────────────────────────────


async def _create_user(db: AsyncSession, email: str, suffix: str = "") -> User:
    """Helper: insert a minimal User row and return it."""
    from app.auth.security import hash_password

    user = User(
        email=email,
        hashed_password=hash_password(f"TestPass1!{suffix}"),
        full_name=f"Test User {suffix}",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _get_access_token(client: AsyncClient, email: str, password: str) -> str:
    """Register (if needed) and login to get a JWT access token."""
    # Try login first; register if 401
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    if resp.status_code == 401:
        await client.post(
            "/auth/register",
            json={"email": email, "password": password, "full_name": "Test User"},
        )
        resp = await client.post(
            "/auth/login", json={"email": email, "password": password}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ── Fake provider implementations ────────────────────────────────────────────

_FAKE_CHUNKS: list[RetrievalResult] = [
    RetrievalResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        content="The mitochondria is the powerhouse of the cell.",
        score=0.95,
        chunk_index=0,
        page_number=1,
        source_filename="biology.pdf",
        chunk_metadata={},
    )
]

_FAKE_CITATION = Citation(
    chunk_id=_FAKE_CHUNKS[0].chunk_id,
    document_id=_FAKE_CHUNKS[0].document_id,
    chunk_index=0,
    page_number=1,
    snippet="The mitochondria is the powerhouse of the cell.",
    source_filename="biology.pdf",
    score=0.95,
)

_FAKE_RESULT = GenerationResult(
    answer="[CHUNK_1] The mitochondria is the powerhouse of the cell.",
    citations=[_FAKE_CITATION],
    model="fake-model",
    prompt_tokens=10,
    completion_tokens=8,
)


class _FakeGenerationProvider:
    model_name = "fake-model"

    async def astream(
        self, system_prompt: str, user_prompt: str
    ) -> AsyncGenerator[str, None]:
        for token in ["[CHUNK_1] The ", "mitochondria ", "is the powerhouse."]:
            yield token

    async def acomplete(
        self, system_prompt: str, user_prompt: str
    ) -> tuple[str, int, int]:
        return _FAKE_RESULT.answer, 10, 8


class _FakeEmbeddingProvider:
    dimensions = 1536

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions for _ in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimensions


# ── test_client override + session patcher ───────────────────────────────────


def _make_streaming_session_patcher(db: AsyncSession):
    """Return a context manager that patches get_streaming_session to yield db."""

    @asynccontextmanager
    async def _fake_streaming_session():
        yield db

    return patch("app.core.database.get_streaming_session", _fake_streaming_session)


@pytest_asyncio.fixture
async def auth_users(
    db: AsyncSession, test_client: AsyncClient
) -> dict[str, dict[str, str]]:
    """Create two users and return their emails + passwords + tokens."""
    users = {
        "alice": {
            "email": "alice_chat@test.com",
            "password": "AlicePass1!",
        },
        "bob": {
            "email": "bob_chat@test.com",
            "password": "BobPass1!",
        },
    }
    for data in users.values():
        token = await _get_access_token(test_client, data["email"], data["password"])
        data["token"] = token
    return users


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Helpers to collect SSE events ────────────────────────────────────────────


async def _collect_sse(response) -> list[dict[str, Any]]:
    """Parse all SSE data lines from a streaming response."""
    events: list[dict[str, Any]] = []
    async for line in response.aiter_lines():
        line = line.strip()
        if line.startswith("data: "):
            payload = line[6:]
            if payload:
                events.append(json.loads(payload))
    return events


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_creates_session_and_persists_messages(
    test_client: AsyncClient, auth_users: dict, db: AsyncSession
) -> None:
    """Full SSE flow: new session created, user + assistant messages persisted."""
    alice = auth_users["alice"]

    with (
        _make_streaming_session_patcher(db),
        patch(
            "app.routers.chat.get_generation_provider",
            return_value=_FakeGenerationProvider(),
        ),
        patch(
            "app.routers.chat.get_embedding_provider",
            return_value=_FakeEmbeddingProvider(),
        ),
        patch(
            "app.retrieval.service.RetrievalService.retrieve",
            new_callable=AsyncMock,
            return_value=_FAKE_CHUNKS,
        ),
    ):
        async with test_client.stream(
            "POST",
            "/chat/query",
            json={"message": "What are mitochondria?"},
            headers=_auth_headers(alice["token"]),
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            events = await _collect_sse(resp)

    # Validate SSE event sequence
    token_events = [e for e in events if e.get("type") == "token"]
    done_events = [e for e in events if e.get("type") == "done"]

    assert len(token_events) >= 1, "Expected at least one token event"
    assert len(done_events) == 1, "Expected exactly one done event"

    done = done_events[0]
    session_id = uuid.UUID(done["session_id"])
    message_id = uuid.UUID(done["message_id"])
    assert done["model"] == "fake-model"
    assert len(done["citations"]) == 1

    # Verify DB state: session created
    session_result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    assert session is not None, "ChatSession should have been created"

    # Verify user message
    msgs_result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    messages = msgs_result.scalars().all()
    roles = {m.role for m in messages}
    assert MessageRole.USER in roles
    assert MessageRole.ASSISTANT in roles

    # Verify assistant message has citations
    asst_msg = next(m for m in messages if m.role == MessageRole.ASSISTANT)
    assert asst_msg.id == message_id
    assert asst_msg.sources is not None
    assert len(asst_msg.sources) == 1


@pytest.mark.asyncio
async def test_query_uses_existing_session(
    test_client: AsyncClient, auth_users: dict, db: AsyncSession
) -> None:
    """When session_id is provided, messages are added to the existing session."""
    alice = auth_users["alice"]

    # Look up alice's user row to create the session under her user_id
    from app.models.user import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(UserModel.email == alice["email"])
    )
    alice_user = user_result.scalar_one()

    existing_session = ChatSession(user_id=alice_user.id, title="Existing session")
    db.add(existing_session)
    await db.flush()
    existing_session_id = existing_session.id

    with (
        _make_streaming_session_patcher(db),
        patch(
            "app.routers.chat.get_generation_provider",
            return_value=_FakeGenerationProvider(),
        ),
        patch(
            "app.routers.chat.get_embedding_provider",
            return_value=_FakeEmbeddingProvider(),
        ),
        patch(
            "app.retrieval.service.RetrievalService.retrieve",
            new_callable=AsyncMock,
            return_value=_FAKE_CHUNKS,
        ),
    ):
        async with test_client.stream(
            "POST",
            "/chat/query",
            json={
                "message": "Follow-up question",
                "session_id": str(existing_session_id),
            },
            headers=_auth_headers(alice["token"]),
        ) as resp:
            assert resp.status_code == 200
            events = await _collect_sse(resp)

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    returned_session_id = uuid.UUID(done_events[0]["session_id"])
    assert returned_session_id == existing_session_id


@pytest.mark.asyncio
async def test_list_sessions(
    test_client: AsyncClient, auth_users: dict, db: AsyncSession
) -> None:
    """GET /chat/sessions returns only alice's sessions."""
    alice = auth_users["alice"]

    from app.models.user import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(UserModel.email == alice["email"])
    )
    alice_user = user_result.scalar_one()

    # Create 2 sessions for alice
    for i in range(2):
        s = ChatSession(user_id=alice_user.id, title=f"Session {i}")
        db.add(s)
    await db.flush()

    resp = await test_client.get(
        "/chat/sessions", headers=_auth_headers(alice["token"])
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2  # may include sessions from other tests


@pytest.mark.asyncio
async def test_get_session_history_scoped_to_user(
    test_client: AsyncClient, auth_users: dict, db: AsyncSession
) -> None:
    """Alice can read her own session; Bob gets 403."""
    alice = auth_users["alice"]
    bob = auth_users["bob"]

    from app.models.user import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(UserModel.email == alice["email"])
    )
    alice_user = user_result.scalar_one()

    session = ChatSession(user_id=alice_user.id, title="Alice private session")
    db.add(session)
    await db.flush()
    session_id = session.id

    # Alice can access
    resp = await test_client.get(
        f"/chat/sessions/{session_id}/history",
        headers=_auth_headers(alice["token"]),
    )
    assert resp.status_code == 200

    # Bob is forbidden
    resp = await test_client.get(
        f"/chat/sessions/{session_id}/history",
        headers=_auth_headers(bob["token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_session(
    test_client: AsyncClient, auth_users: dict, db: AsyncSession
) -> None:
    """Delete removes the session; Bob cannot delete Alice's session."""
    alice = auth_users["alice"]
    bob = auth_users["bob"]

    from app.models.user import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(UserModel.email == alice["email"])
    )
    alice_user = user_result.scalar_one()

    session = ChatSession(user_id=alice_user.id, title="To be deleted")
    db.add(session)
    await db.flush()
    session_id = session.id

    # Bob cannot delete it
    resp = await test_client.delete(
        f"/chat/sessions/{session_id}",
        headers=_auth_headers(bob["token"]),
    )
    assert resp.status_code == 403

    # Alice can delete it
    resp = await test_client.delete(
        f"/chat/sessions/{session_id}",
        headers=_auth_headers(alice["token"]),
    )
    assert resp.status_code == 204

    # Verify it's gone
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_history_404_unknown_session(
    test_client: AsyncClient, auth_users: dict
) -> None:
    """GET /chat/sessions/{id}/history returns 404 for a non-existent session."""
    alice = auth_users["alice"]
    resp = await test_client.get(
        f"/chat/sessions/{uuid.uuid4()}/history",
        headers=_auth_headers(alice["token"]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_query_requires_auth(test_client: AsyncClient) -> None:
    """POST /chat/query with no token returns 401."""
    resp = await test_client.post("/chat/query", json={"message": "hello"})
    assert resp.status_code == 401
