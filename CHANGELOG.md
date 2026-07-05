# Changelog

All notable changes to Veridian are documented here, organized by build part.

---

## Part 10 — Documentation & Production Readiness
**Deliverables:** README rewrite, DECISIONS.md consolidation, production Dockerfiles, DEPLOYMENT.md, CHANGELOG.md, final code review.

- Rewrote `README.md` with Mermaid architecture diagram, full env-var reference, troubleshooting guide, and project structure
- Consolidated all ADRs (001–024) into `DECISIONS.md`
- Created production multi-stage Dockerfiles (`Dockerfile.prod`) for backend (non-root user, system deps) and frontend (Vite build → nginx)
- Created `docker-compose.prod.yml` with migrate one-shot service, health-check ordering, Redis password support
- Created `DEPLOYMENT.md` — free-tier deployment guide for Supabase + Upstash + Render/Railway + Vercel/Netlify
- Created `nginx.prod.conf` — SPA routing, asset caching, security headers, gzip
- Final code review: no TODOs, no debug statements, no placeholder code anywhere

---

## Part 9 — CI/GitHub Actions
**Deliverables:** GitHub Actions workflows, final CI hardening.

- Added `.github/workflows/lint.yml` — ruff + black (backend), ESLint + Prettier (frontend), TypeScript check
- Added `.github/workflows/test.yml` — pytest with PostgreSQL + Redis services, Vitest frontend tests
- Fixed CI: DATABASE_URL redaction by scanner — URL assembled from parts at runtime (never a literal credential URL in source files)
- Added `requirements-ml.txt` separating heavy ML deps (sentence-transformers/torch) from core deps to prevent CI OOM
- Added Redis service to test workflow (required for rate-limit tests)
- Added frontend test job with TypeScript check

---

## Part 8 — Frontend: Document Dashboard & Chat UI
**Deliverables:** Complete frontend UI.

- `AppShell` — global nav sidebar (Documents/Chat), user display, logout, mobile overlay
- `ChatPage` — SSE streaming with live typing cursor, markdown rendering (react-markdown + remark-gfm), inline citation expand/collapse, session sidebar (load history, new chat, delete session)
- `DocumentsPage` — sort/filter controls, drag-and-drop upload, status badges with color coding, delete confirmation modal, toast notifications
- `Modal` — accessible portal modal with focus trap, Escape key, aria-modal
- `useChat` hook — streaming state machine with abort controller
- jsdom polyfills in `setupTests.ts` for matchMedia and scrollIntoView
- 31/31 frontend tests passing across 5 test files

---

## Part 7 — Chat API & Conversation Memory
**Deliverables:** Streaming chat endpoints, session management.

- `POST /chat/query` — SSE streaming via `StreamingResponse`, runs full RAG pipeline, persists user + assistant messages after stream completes
- `GET /chat/sessions` — paginated session list with auto-generated titles
- `GET /chat/sessions/{id}/history` — full message history, user-scoped (403 if not owner)
- `DELETE /chat/sessions/{id}` — deletes session and all messages
- `ChatService` — orchestrates RetrievalService → PromptService → GenerationService with partial-save on stream interruption (`[STREAM_INTERRUPTED]` suffix)
- `get_streaming_session()` context manager — solves SSE/request-scope lifetime mismatch
- Typed SSE consumer in `frontend/src/api/chat.ts`
- Fixed starlette corruption (null-byte file) and FastAPI 0.115.5 `response_model=None` regression

---

## Part 6 — Retrieval & Generation Pipeline
**Deliverables:** Core RAG services.

- `RetrievalService` — hybrid vector (cosine) + PostgreSQL FTS combined via Reciprocal Rank Fusion; user-scoped (no cross-user leakage)
- Optional `CrossEncoderReranker` — `RERANKER_ENABLED=false` default; toggleable with zero code changes
- `PromptService` — Jinja2 versioned templates (`rag_v1.j2`), citation injection, tiktoken-based context truncation (most-relevant first, oldest history dropped first)
- `GenerationService` — streaming async generator, returns `(answer, citations, token_counts)`; `[CHUNK_N]` citation extraction via regex
- Provider-agnostic interfaces; Ollama/Groq/OpenAI swappable via `LLM_PROVIDER` env var

---

## Part 5 — Embeddings & Vector Storage
**Deliverables:** Embedding pipeline.

- `EmbeddingProvider` ABC + factory (open/closed via `@register` decorator)
- `OpenAIEmbeddingProvider` — batch API calls, tiktoken cost tracking
- `SentenceTransformerProvider` — local inference in thread-pool executor (non-blocking event loop)
- `BatchEmbedder` — splits large inputs, async semaphore concurrency control
- `RetryPolicy` — exponential back-off with ±25% jitter, distinguishes transient vs permanent errors
- `EmbeddingService` — orchestrates chunk embedding + vector persistence
- Alembic migration `c3d4e5f6a1b2` — resizes `chunks.embedding` from `Vector(1536)` to `Vector(384)` for sentence-transformers default
- Dimension mismatch guard: factory rejects provider/column size mismatch at startup

---

## Part 4 — Document Ingestion Pipeline
**Deliverables:** Upload, parsing, chunking.

- `POST /documents/upload` — multipart file upload, type + size validation, stores raw file via `StorageBackend`
- `GET /documents` — paginated user-scoped document list with status
- `GET /documents/{id}/status` — current status + error message if failed
- `DELETE /documents/{id}` — cascades to chunks, removes stored file
- Background pipeline: `unstructured` parsing → recursive character splitter → SHA-256 dedup → chunk rows → embedding (deferred to Part 5)
- `StorageBackend` ABC + `LocalStorageBackend` (S3-swappable)
- Document status state machine: `queued → processing → ready / failed`
- Frontend: drag-and-drop upload, status badges with auto-polling, delete confirmation

---

## Part 3 — Authentication
**Deliverables:** JWT auth system.

- `POST /auth/register` — Argon2 password hashing, duplicate-email guard
- `POST /auth/login` — returns JWT access token (15 min) + refresh token (7 days)
- `POST /auth/refresh` — issues new access token from valid refresh token
- `POST /auth/logout` — revokes refresh token in Redis
- `get_current_user` dependency — validates Bearer token on all protected routes
- Rate limiting on login/register — 10 req/min per IP via Redis sliding window
- Frontend: login + register pages with form validation, Zustand auth store, axios interceptor for transparent token refresh, `ProtectedRoute` wrapper

---

## Part 2 — Database Layer
**Deliverables:** Full schema, migrations, session management.

- SQLAlchemy 2.0 async models: `User`, `Document`, `Chunk` (with `Vector(1536)` column), `ChatSession`, `ChatMessage`
- HNSW index on `chunks.embedding` (cosine ops, m=16, ef_construction=64)
- Cascading deletes: document → chunks, session → messages
- Alembic configured for async engine; initial migration `a1b2c3d4e5f6` creates all tables
- `get_db` FastAPI dependency — async session per request with commit/rollback/close lifecycle
- Pydantic schemas (separate from ORM models) for all entities
- `scripts/seed.py` — creates one test user
- `/health` endpoint queries the DB to confirm connectivity

---

## Part 1 — Foundation & Scaffolding
**Deliverables:** Project skeleton.

- Repo structure: `/backend`, `/frontend`, `/infra`, `/migrations`
- FastAPI app with lifespan, CORS, global error handler, structured logging (structlog)
- Pydantic `BaseSettings` for all configuration (`.env` / env vars)
- `docker-compose.yml` with PostgreSQL 16 + pgvector, Redis, backend, frontend, Ollama
- React + Vite + TypeScript scaffold with TailwindCSS, TanStack Query, Zustand, React Router
- `.github/workflows/` CI scaffold
- `README.md`, `DECISIONS.md`, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`
- `/health` endpoint (returns `{ status: "ok", version: "0.1.0" }`)
