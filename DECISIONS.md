# Architecture Decision Records — Veridian

This document consolidates every significant design decision made across the 10-part build. Each entry follows the ADR format: context, decision, rationale, and trade-offs.

---

## Infrastructure & Stack

### ADR-001 — PostgreSQL + pgvector over a dedicated vector store
**Decision:** Use pgvector inside PostgreSQL rather than Pinecone, Weaviate, Qdrant, or Chroma.
**Rationale:** One fewer service to operate. Transactional consistency between metadata and vectors is free. HNSW index is sufficient for RAG workloads up to ~10 M vectors.
**Trade-off:** At 100 M+ vectors a dedicated ANN engine may outperform pgvector. The `RetrievalService` interface makes this swappable without changing callers.

### ADR-002 — structlog for structured logging
**Decision:** structlog over stdlib logging.
**Rationale:** Machine-parseable JSON logs; context binding propagates request IDs through async chains without thread-local hacks; stdlib integration captures third-party log output.

### ADR-003 — Pydantic v2 + pydantic-settings
**Decision:** Pydantic v2 (not v1) for all schemas; pydantic-settings for config.
**Rationale:** V2 is 5-50x faster. BaseSettings was extracted to pydantic-settings in V2. SettingsConfigDict gives better IDE support than the inner Config class.

### ADR-004 — App factory pattern (create_app())
**Decision:** FastAPI instance created via create_app(), not a module-level global.
**Rationale:** Tests can instantiate the app with different settings without patching globals. Prevents import-time side effects from running during test collection.

### ADR-005 — asyncpg as the async PostgreSQL driver
**Decision:** asyncpg via sqlalchemy[asyncio] over psycopg3.
**Rationale:** asyncpg is more battle-tested with SQLAlchemy 2.0. Native binary protocol. Larger production track record at time of decision.

---

## Database Schema

### ADR-006 — HNSW index over IVFFlat for vector search
**Decision:** HNSW (m=16, ef_construction=64) on chunks.embedding.
**Rationale:** HNSW offers better recall at comparable or lower query latency than IVFFlat for <10 M vectors. IVFFlat requires an explicit training step (VACUUM ANALYZE + cluster); HNSW builds incrementally. For this RAG workload query latency matters more than index build time.

---

## Auth

### ADR-007 — JWT + Redis refresh token revocation
**Decision:** Short-lived JWT access tokens (15 min) + server-side refresh tokens stored in Redis.
**Rationale:** Stateless access tokens allow horizontal scaling. Server-side refresh tokens enable revocation (logout invalidates the token immediately). Redis TTL automatically expires old tokens.

### ADR-008 — Argon2 for password hashing
**Decision:** argon2-cffi over bcrypt or scrypt.
**Rationale:** Argon2 won the Password Hashing Competition. Memory-hard by design; resistant to GPU/ASIC attacks. argon2-cffi is the reference Python binding.

---

## Document Ingestion

### ADR-009 — StorageBackend ABC for file storage
**Decision:** Abstract file storage behind a StorageBackend interface (save/load/delete/exists) with LocalStorageBackend as the initial implementation.
**Rationale:** Calling code is completely agnostic to the storage medium. Swapping to S3/GCS requires only a new class and changing the get_storage() dependency — zero changes to routers or the ingestion pipeline.

### ADR-010 — FastAPI BackgroundTasks for ingestion (not Celery/RQ)
**Decision:** Use FastAPI BackgroundTasks to run ingestion immediately after the upload response.
**Rationale:** Zero additional infrastructure for the current single-node, low-throughput use case. The _run_pipeline() function is already extracted from any FastAPI context — migrating to Celery later requires zero changes to the pipeline itself.
**When to reconsider:** p99 ingestion time > 30 s, memory pressure, or need for retries/dead-letter queues.

### ADR-011 — SHA-256 content hash for deduplication
**Decision:** Compute SHA-256 of raw file bytes and store in documents.content_hash.
**Rationale:** Prevents re-ingesting the same file. Hash is computed before storage write (no wasted I/O). Per-user scope: two users uploading the same file each get their own row.

### ADR-012 — unstructured for document parsing
**Decision:** Use the unstructured library for text extraction.
**Rationale:** Single API handles PDF, DOCX, TXT, MD, HTML with automatic format detection. Emits structured Element objects with page numbers.
**Trade-off:** Heavy dependency (~100 MB). Full PDF support requires poppler-utils and libmagic at the OS level (installed in Dockerfile.prod).

---

## Embeddings

### ADR-013 — sentence-transformers as default embedding provider (free)
**Decision:** all-MiniLM-L6-v2 (384 dims) via sentence-transformers as the default.
**Rationale:** Runs entirely on-device; no API key, no cost, no rate limits. 384-dim vectors are sufficient for RAG at this scale. The EmbeddingProvider interface makes switching to OpenAI (1536 dims) a one-line env change + migration.
**Previous default:** OpenAI text-embedding-3-small (1536 dims) — changed in Part 10 to align with free-tier requirement.

### ADR-014 — SOLID-compliant embedding layer
**Decision:** Five classes with distinct responsibilities.

| Class | Responsibility |
|-------|---------------|
| EmbeddingProvider ABC | Contract definition |
| RetryPolicy | Back-off timing only |
| BatchEmbedder | Splitting + concurrency |
| EmbeddingProviderFactory | Registry-based creation |
| EmbeddingService | Orchestration + persistence |

**OCP:** New providers register via @EmbeddingProviderFactory.register("name") without touching the factory.
**DI:** _run_pipeline() accepts an optional EmbeddingService — tests inject mocks; production uses the real service.

### ADR-015 — Manual retry policy (no tenacity)
**Decision:** asyncio.sleep-based exponential back-off in RetryPolicy, not tenacity.
**Rationale:** Avoids an extra dependency for simple logic. RetryPolicy is fully unit-testable with 0 ms delays. TransientEmbeddingError → retry; EmbeddingError → reraise immediately.

---

## Retrieval

### ADR-016 — Hybrid retrieval with Reciprocal Rank Fusion
**Decision:** Combine vector (cosine similarity) and keyword (PostgreSQL FTS) using Reciprocal Rank Fusion (RRF, k=60).
**Rationale:** Vector search misses exact-match queries; FTS misses semantic ones. RRF merges ranked lists without score normalization (cosine and ts_rank are on incompatible scales). RRF with k=60 consistently outperforms weighted combination in BEIR benchmarks.
**Config:** HYBRID_SEARCH_ENABLED=true (default). Set false to use vector only.

### ADR-017 — Optional CrossEncoder reranking
**Decision:** Cross-encoder reranking disabled by default (RERANKER_ENABLED=false).
**Model:** cross-encoder/ms-marco-MiniLM-L-6-v2 (~22 M params, CPU-compatible).
**Rationale:** Adds 5-10 pp nDCG@10 improvement but 100-500 ms latency. NoopReranker pass-through ensures zero overhead when disabled.
**When to enable:** Legal/medical use cases where precision matters more than latency.

---

## Generation

### ADR-018 — Ollama as default LLM (free forever)
**Decision:** Ollama (llama3.2:3b, local inference) as the default LLM provider.
**Rationale:** Runs entirely on-device. No API key, no rate limits, no cost ever. ~2 GB model download cached in a Docker volume. LangChain ChatOllama provides the same streaming interface as ChatOpenAI.
**Alternatives:** Groq (free tier, 30 req/min), OpenAI (paid). Both supported via LLM_PROVIDER env var.
**Previous default:** OpenAI gpt-4o-mini — changed to align with free-tier requirement.

### ADR-019 — Jinja2 versioned prompt templates
**Decision:** Prompt templates as .j2 files in app/prompts/templates/, versioned by filename.
**Rationale:** Inline f-strings scatter prompt logic and are hard to diff/review. Jinja2 templates are testable in isolation and support conditionals (if history, if citations).

### ADR-020 — [CHUNK_N] citation protocol
**Decision:** Instruct LLM to cite via [CHUNK_N] markers; extract via regex post-generation.
**Rationale:** More reliable than asking the LLM to output JSON citations (which can fail mid-stream). Regex extraction works with streaming and adds zero overhead for non-citing responses.

---

## Chat API

### ADR-021 — SSE over WebSocket for streaming
**Decision:** Server-Sent Events via StreamingResponse for chat token streaming.
**Rationale:** Generation is unidirectional (server to client). SSE uses plain HTTP with no upgrade handshake — works through any proxy or load balancer. FastAPI handles it natively.
**Trade-off:** If client-side cancellation mid-stream is needed, SSE requires a separate DELETE request. WebSocket would be cleaner then.

### ADR-022 — Partial-save on stream interruption
**Decision:** On stream failure, save partial response with [STREAM_INTERRUPTED] suffix.
**Rationale:** Better UX than discarding (user sees what was generated). Session history stays coherent for future turns. The assistant message is always closed.

### ADR-023 — Streaming session opens its own DB session
**Decision:** SSE generator opens a fresh AsyncSession via get_streaming_session(), not the request-scoped get_db dependency.
**Rationale:** FastAPI closes the request-scoped session when the route handler returns — before the StreamingResponse body is consumed. get_streaming_session() is a context manager that lives for the generator's lifetime.

---

## Developer Experience

### ADR-024 — response_model=None on all HTTP 204 endpoints
**Issue:** FastAPI 0.115.5 + from __future__ import annotations: -> None return annotation is stored as the string 'None'. FastAPI evaluates this via ForwardRef, gets NoneType (the class, which is truthy), then asserts is_body_allowed_for_status_code(204) — which fails.
**Fix:** Add response_model=None explicitly to every endpoint with status_code=HTTP_204_NO_CONTENT.