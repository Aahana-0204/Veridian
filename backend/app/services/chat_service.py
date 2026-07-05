"""ChatService: orchestrates one RAG query turn end-to-end.

Responsibilities (SRP)
-----------------------
1. Create or retrieve the ``ChatSession`` row for this conversation.
2. Persist the user's message immediately (so it survives streaming failures).
3. Load recent history and pass it to ``PromptService`` for context.
4. Run the RAG pipeline: retrieve → prompt → stream generation.
5. Persist the assistant's response (with citations) on stream completion.
6. Yield SSE-ready event dicts to the calling router.

Streaming failure handling
--------------------------
If generation fails mid-stream (network error, timeout, provider outage),
the partial response accumulated so far is saved with a ``[STREAM_INTERRUPTED]``
suffix.  This ensures:
  - No silent data loss — the user sees what was generated.
  - The DB record is always closed (never left in a "generating" limbo).
  - The session history remains coherent for future turns.

Design (SOLID)
--------------
- **D** — Depends on ``RetrievalService``, ``PromptService``,
  ``GenerationService`` abstractions.  Concrete implementations are
  injected by the router factory.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.service import GenerationService
from app.models.chat import ChatMessage, ChatSession, MessageRole
from app.prompts.service import PromptService
from app.retrieval.service import RetrievalService
from app.schemas.chat import ChatDoneEvent, ChatErrorEvent, ChatTokenEvent
from app.schemas.rag import ChatTurn, Citation, GenerationResult

logger = structlog.get_logger(__name__)

_SESSION_TITLE_MAX = 80  # chars — auto-generated from first user message


class ChatService:
    """Runs a single RAG query turn and streams events to the caller.

    Parameters
    ----------
    retrieval_svc:
        Configured ``RetrievalService`` (retriever + reranker).
    prompt_svc:
        Configured ``PromptService`` (template + truncation settings).
    generation_svc:
        Configured ``GenerationService`` wrapping the LLM provider.
    """

    def __init__(
        self,
        retrieval_svc: RetrievalService,
        prompt_svc: PromptService,
        generation_svc: GenerationService,
    ) -> None:
        self._retrieval = retrieval_svc
        self._prompt = prompt_svc
        self._generation = generation_svc

    # ── Public API ────────────────────────────────────────────────────────────

    async def stream_query(
        self,
        query: str,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run the full pipeline and yield SSE-ready event dicts.

        Yields
        ------
        dict
            One of:
            - ``{"type": "token", "content": "..."}``
            - ``{"type": "done", "session_id": ..., "message_id": ..., ...}``
            - ``{"type": "error", "message": "..."}``  (on failure)
        """
        # 1. Create or retrieve session
        chat_session = await self._get_or_create_session(session_id, user_id, query, db)

        # 2. Persist user message immediately
        user_msg = ChatMessage(
            session_id=chat_session.id,
            user_id=user_id,
            role=MessageRole.USER,
            content=query,
        )
        db.add(user_msg)
        await db.flush()

        # 3. Load history (excluding the just-added user message)
        history = await self._load_history(chat_session.id, db, exclude_id=user_msg.id)

        # 4. Retrieve relevant chunks
        chunks = await self._retrieval.retrieve(query, user_id, db)

        # 5. Build prompt
        prompt = self._prompt.build_prompt(query=query, chunks=chunks, history=history)

        # 6. Stream generation, accumulate, then persist
        accumulated: list[str] = []
        result: GenerationResult | None = None
        interrupted = False

        try:
            async for item in self._generation.stream_generate(prompt, chunks):
                if isinstance(item, str):
                    accumulated.append(item)
                    yield ChatTokenEvent(content=item).model_dump()
                elif isinstance(item, GenerationResult):
                    result = item
        except Exception as exc:
            interrupted = True
            logger.error(
                "chat_stream_interrupted",
                session_id=str(chat_session.id),
                error=str(exc),
                exc_info=exc,
            )
            yield ChatErrorEvent(
                message=f"Generation interrupted: {type(exc).__name__}"
            ).model_dump()

        # 7. Persist assistant message (always, even on partial/interrupted)
        full_text = "".join(accumulated)
        if interrupted:
            full_text = (
                full_text or "(No response generated)"
            ) + " [STREAM_INTERRUPTED]"

        citations: list[Citation] = result.citations if result else []
        asst_msg = ChatMessage(
            session_id=chat_session.id,
            user_id=user_id,
            role=MessageRole.ASSISTANT,
            content=full_text,
            sources=(
                [c.model_dump(mode="json") for c in citations] if citations else None
            ),
            token_count=result.completion_tokens if result else None,
        )
        db.add(asst_msg)
        await db.flush()

        if result and not interrupted:
            yield ChatDoneEvent(
                session_id=chat_session.id,
                message_id=asst_msg.id,
                citations=citations,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            ).model_dump(mode="json")

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _get_or_create_session(
        self,
        session_id: uuid.UUID | None,
        user_id: uuid.UUID,
        first_message: str,
        db: AsyncSession,
    ) -> ChatSession:
        """Return an existing session (verified to belong to user) or create one."""
        if session_id is not None:
            result = await db.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == user_id,
                )
            )
            chat_session = result.scalar_one_or_none()
            if chat_session is None:
                # Session not found or doesn't belong to user → create new
                logger.warning(
                    "chat_session_not_found_creating_new",
                    requested_session_id=str(session_id),
                    user_id=str(user_id),
                )
                session_id = None

        if session_id is None:
            title = first_message[:_SESSION_TITLE_MAX].strip() or "New Chat"
            chat_session = ChatSession(user_id=user_id, title=title)
            db.add(chat_session)
            await db.flush()
            logger.info(
                "chat_session_created",
                session_id=str(chat_session.id),
                user_id=str(user_id),
            )

        return chat_session

    async def _load_history(
        self,
        session_id: uuid.UUID,
        db: AsyncSession,
        exclude_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[ChatTurn]:
        """Load recent messages from the session as ``ChatTurn`` objects."""
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
        )
        if exclude_id is not None:
            stmt = stmt.where(ChatMessage.id != exclude_id)

        result = await db.execute(stmt)
        messages = result.scalars().all()

        return [ChatTurn(role=msg.role.value, content=msg.content) for msg in messages]
