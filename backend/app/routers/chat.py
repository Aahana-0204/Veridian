"""Chat router: REST + SSE streaming endpoints for the RAG conversation API.

Endpoints
---------
POST   /chat/query                   — Send a query; streams the response via SSE.
GET    /chat/sessions                — Paginated list of the user's chat sessions.
GET    /chat/sessions/{id}/history   — Full message history for a session.
DELETE /chat/sessions/{id}           — Delete a session and its messages.

Streaming design
----------------
Server-Sent Events (SSE) are used instead of WebSocket because:
  - Generation is unidirectional (server → client).
  - SSE works transparently through HTTP proxies and load balancers.
  - No connection upgrade handshake; simpler infrastructure requirements.
  See DECISIONS.md ADR-020 for full rationale.

Session management
------------------
The SSE event generator opens its own DB session (``get_streaming_session``)
because FastAPI's request-scoped ``get_db`` session is closed when the
endpoint handler returns — before the ``StreamingResponse`` body is consumed.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db, get_streaming_session
from app.core.deps import get_current_active_user
from app.embeddings.base import EmbeddingProvider
from app.embeddings.deps import get_embedding_provider
from app.generation.base import GenerationProvider
from app.generation.factory import build_generation_provider
from app.generation.service import GenerationService
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.prompts.service import PromptService
from app.reranking.factory import build_reranker
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.keyword import KeywordRetriever
from app.retrieval.service import RetrievalService
from app.retrieval.vector import VectorRetriever
from app.schemas.chat import (
    ChatErrorEvent,
    ChatMessageResponse,
    ChatQueryRequest,
    ChatSessionListResponse,
    ChatSessionResponse,
)
from app.services.chat_service import ChatService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Provider dependencies ─────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_gen_provider() -> GenerationProvider:
    return build_generation_provider(get_settings())


def get_generation_provider() -> GenerationProvider:
    """FastAPI dependency: singleton generation provider."""
    return _build_gen_provider()


def _build_retrieval_service(
    emb_provider: EmbeddingProvider,
) -> RetrievalService:
    settings = get_settings()
    vector_ret = VectorRetriever(embedding_provider=emb_provider)
    keyword_ret = KeywordRetriever()

    retriever: Any
    if settings.hybrid_search_enabled:
        retriever = HybridRetriever(
            vector_retriever=vector_ret,
            keyword_retriever=keyword_ret,
            candidate_multiplier=settings.retrieval_candidate_multiplier,
        )
    else:
        retriever = vector_ret

    reranker = build_reranker(settings)
    return RetrievalService(
        retriever=retriever,
        reranker=reranker,
        top_k=settings.top_k,
        reranker_top_n_multiplier=settings.reranker_top_n_multiplier,
    )


def _build_chat_service(
    emb_provider: EmbeddingProvider,
    gen_provider: GenerationProvider,
) -> ChatService:
    settings = get_settings()
    retrieval_svc = _build_retrieval_service(emb_provider)
    prompt_svc = PromptService(
        template_name=settings.prompt_template,
        max_context_tokens=settings.max_context_tokens,
        max_history_tokens=settings.max_history_tokens,
        model=settings.llm_model,
    )
    gen_svc = GenerationService(gen_provider)
    return ChatService(retrieval_svc, prompt_svc, gen_svc)


# ── SSE helper ────────────────────────────────────────────────────────────────


def _sse_data(payload: dict[str, Any]) -> str:
    """Format a dict as a single SSE ``data:`` line."""
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/query")
async def query_chat(
    body: ChatQueryRequest,
    current_user: User = Depends(get_current_active_user),
    emb_provider: EmbeddingProvider = Depends(get_embedding_provider),
    gen_provider: GenerationProvider = Depends(get_generation_provider),
) -> StreamingResponse:
    """Stream a RAG answer for the user's query via Server-Sent Events.

    The response is a ``text/event-stream`` with three event types:

    - ``{"type": "token", "content": "..."}`` — incremental tokens
    - ``{"type": "done", "session_id": ..., "message_id": ..., ...}`` — final
    - ``{"type": "error", "message": "..."}`` — terminal error

    A new ``ChatSession`` is created if ``session_id`` is not provided.
    """
    user_id: uuid.UUID = current_user.id

    # Build services once (captured in closure — stateless, safe to share)
    chat_svc = _build_chat_service(emb_provider, gen_provider)

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async with get_streaming_session() as db:
                async for event_dict in chat_svc.stream_query(
                    query=body.message,
                    user_id=user_id,
                    session_id=body.session_id,
                    db=db,
                ):
                    yield _sse_data(event_dict)
        except Exception as exc:
            logger.error("sse_outer_error", error=str(exc), exc_info=exc)
            yield _sse_data(
                ChatErrorEvent(message="Internal server error").model_dump()
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    """Return a paginated list of the current user's chat sessions."""
    offset = (page - 1) * size

    total_result = await db.execute(
        select(func.count()).where(ChatSession.user_id == current_user.id)
    )
    total: int = total_result.scalar_one()

    sessions_result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    sessions = sessions_result.scalars().all()

    return ChatSessionListResponse(
        items=[ChatSessionResponse.model_validate(s) for s in sessions],
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)),
    )


@router.get("/sessions/{session_id}/history", response_model=ChatSessionResponse)
async def get_session_history(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    """Return full message history for a session.

    Returns 404 if the session does not exist, 403 if it belongs to another user.
    """
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    # Load messages
    msgs_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = msgs_result.scalars().all()

    session_response = ChatSessionResponse.model_validate(session)
    session_response.messages = [
        ChatMessageResponse.model_validate(m) for m in messages
    ]
    return session_response


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a chat session and all its messages (cascade from Part 2 model)."""
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    await db.delete(session)
    logger.info(
        "chat_session_deleted", session_id=str(session_id), user_id=str(current_user.id)
    )
