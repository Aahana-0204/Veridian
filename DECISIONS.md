# Architecture Decisions

This file records significant design choices made throughout the project. Each entry explains the decision, the alternatives considered, and the trade-offs accepted.

---

## Part 1: Foundation & Scaffolding

### ADR-001 — PostgreSQL + pgvector instead of a dedicated vector DB

**Decision:** Store document embeddings in PostgreSQL using the `pgvector` extension rather than a dedicated vector store (Pinecone, Weaviate, Qdrant, Chroma).

**Rationale:**
- Keeps the operational footprint minimal — one fewer service to operate, monitor, and back up.
- Transactional consistency between document metadata and their embeddings comes for free.
- pgvector supports HNSW and IVFFlat indexes, sufficient for most RAG workloads up to ~10 M vectors.

**Trade-off:** At very large scale (100 M+ vectors), a dedicated ANN engine may outperform pgvector. This can be swapped out without changing the application interface layer.

---

### ADR-002 — structlog for structured JSON logging

**Decision:** Use `structlog` instead of Python's built-in `logging` module directly.

**Rationale:**
- Produces machine-parseable JSON logs out of the box — essential for log aggregators (Loki, Datadog, etc.).
- Context binding (`structlog.contextvars`) propagates request IDs and user IDs through async call chains without threading hacks.
- `stdlib` integration means third-party libraries that use `logging.getLogger` still emit structured output.

---

### ADR-003 — Pydantic v2 + pydantic-settings

**Decision:** Use Pydantic v2 (not v1) for all schemas and `pydantic-settings` for environment config.

**Rationale:**
- V2 is ~5–50× faster than V1 for validation.
- `BaseSettings` was extracted to `pydantic-settings` in V2 to keep the core lean.
- The `model_config = SettingsConfigDict(...)` pattern replaces the inner `Config` class for better IDE support.

---

### ADR-004 — App factory pattern (`create_app()`)

**Decision:** Expose the FastAPI instance via a `create_app()` function rather than a module-level global.

**Rationale:**
- Tests can instantiate the app with different `Settings` overrides (e.g., test DB, disabled auth) without patching globals.
- Prevents import-time side effects (middleware registration, logging config) from running at module load in tests.

---

### ADR-005 — asyncpg as the async PostgreSQL driver

**Decision:** Use `asyncpg` (via `sqlalchemy[asyncio]`) rather than `psycopg3`.

**Rationale:**
- `asyncpg` is the most battle-tested async Postgres driver in the Python ecosystem.
- Has native binary protocol support and excellent SQLAlchemy 2.0 integration.
- `psycopg3` is newer and promising but asyncpg has a larger production track record at this time.

---

## Part 6: Retrieval & Generation Pipeline

### ADR-015 — Hybrid retrieval with Reciprocal Rank Fusion (RRF)

**Decision:** Combine vector (cosine similarity) and keyword (PostgreSQL FTS) retrievers using Reciprocal Rank Fusion.

**Rationale:**
- Vector search excels at semantic queries ("how does X work?") but misses exact matches ("error code 404").
- PostgreSQL FTS (`ts_rank` / `to_tsvector`) provides BM25-style tf-idf scoring with zero additional infrastructure.
- RRF merges the two ranked lists without score normalization — vector cosine scores (0–1) and ts_rank scores are on incompatible scales; RRF uses only rank positions.
- RRF with k=60 consistently outperforms weighted score combination in BEIR benchmarks (Cormack et al. 2009).

**Configuration:** `HYBRID_SEARCH_ENABLED=true` (default). When `false`, only the vector retriever is used.

---

### ADR-016 — Re-ranking with CrossEncoder (disabled by default)

**Decision:** Offer an optional cross-encoder re-ranking stage (`RERANKER_ENABLED=false` by default).

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (~22M params, CPU-compatible).

**Trade-off:** Cross-encoder re-ranking improves nDCG@10 by ~5–10 pp but adds 100–500 ms latency per query depending on candidate count and hardware. The `NoopReranker` pass-through ensures zero overhead when disabled.

**When to enable:** High-precision use cases (legal, medical), or when retrieval quality is more important than p99 latency.

---

### ADR-017 — OpenAI gpt-4o-mini as default LLM

**Decision:** Use `gpt-4o-mini` via LangChain `ChatOpenAI`.

**Rationale:**
- ~$0.15/1M input tokens — 4× cheaper than GPT-4o with comparable quality for RAG tasks.
- 128k context window — accommodates large retrieved context.
- Native streaming via LangChain `astream`.
- LangChain abstraction means swapping to Anthropic/Mistral requires only a new `GenerationProvider` module.

---

### ADR-018 — Jinja2 versioned prompt templates

**Decision:** Store prompt templates as `.j2` files in `app/prompts/templates/`, versioned by filename (e.g. `rag_v1.j2`).

**Rationale:** Inline f-strings scatter prompt logic across the codebase and are hard to review/version. Jinja2 templates are diff-able, testable in isolation, and support conditionals (e.g. `{% if history %}`).

**Token truncation strategy:** Most-relevant chunks first (already ranked), oldest history turns dropped first. tiktoken for exact token counts; char/4 fallback for non-OpenAI models.

---

### ADR-019 — [CHUNK_N] citation protocol

**Decision:** Instruct the LLM to cite sources using `[CHUNK_N]` markers, then extract them via regex after generation.

**Rationale:** Structured post-processing is more reliable than asking the LLM to output JSON citations (which can fail mid-stream). The regex approach works with streaming and adds zero prompt overhead for non-citing responses.


### ADR-011 — OpenAI text-embedding-3-small as default embedding model

**Decision:** Use OpenAI `text-embedding-3-small` (1536 dimensions) as the default embedding provider.

**Rationale:**
- 1536 dimensions exactly matches the `chunks.embedding Vector(1536)` column created in Part 2 — no Alembic migration required.
- ~5× cheaper than `text-embedding-ada-002` with better quality benchmarks.
- Async API with native batch support (up to 2048 inputs per request).
- Swappable to `text-embedding-3-large` (3072 dims) or a local model via `EMBEDDING_PROVIDER` env var.

**Trade-off:** Requires an `OPENAI_API_KEY` in production. For fully offline deployments, set `EMBEDDING_PROVIDER=sentence-transformers` (see ADR-012).

---

### ADR-012 — SentenceTransformers as offline fallback

**Decision:** Implement a `SentenceTransformerProvider` as an optional alternative to the OpenAI provider.

**Usage:** Set `EMBEDDING_PROVIDER=sentence-transformers` and `EMBEDDING_DIMENSIONS=384` in `.env`, then run:

```bash
alembic revision --autogenerate -m "resize_embedding_dim_384"
alembic upgrade head
```

**Default model:** `all-MiniLM-L6-v2` (384 dims). Override with `SENTENCE_TRANSFORMER_MODEL=<hf-model-id>`.

**Trade-off:** Lower embedding quality than OpenAI for multi-domain documents; no API cost; requires GPU/CPU memory for inference.

---

### ADR-013 — SOLID-compliant embedding layer architecture

**Decision:** Structure the embedding layer as five separate classes following SOLID principles.

| Class | Responsibility (SRP) |
|-------|----------------------|
| `EmbeddingProvider` ABC | Defines the embedding contract |
| `RetryPolicy` | Exponential back-off timing only |
| `BatchEmbedder` | Splitting + concurrency only |
| `EmbeddingProviderFactory` | Registry-based creation (OCP) |
| `EmbeddingService` | Orchestrates chunk embedding + flush |

**OCP detail:** New providers register via `@EmbeddingProviderFactory.register("name")` decorator in their own modules. The factory never changes.

**DI detail:** `_run_pipeline` accepts an optional `EmbeddingService` parameter — tests inject a mock service; production code injects the real service built from settings.

---

### ADR-014 — Manual retry policy (no tenacity)

**Decision:** Implement exponential back-off in `RetryPolicy` using `asyncio.sleep` directly rather than the `tenacity` library.

**Rationale:**
- Avoids an additional dependency for straightforward retry logic.
- `RetryPolicy` is fully unit-testable with 0 ms delays by setting `base_delay=0.0`.
- The class is small (~60 LOC) and self-documenting.

**Retry behaviour:**
- `TransientEmbeddingError` → retry with exponential back-off + ±25 % jitter
- `EmbeddingError` → re-raise immediately (no retry)
- Any other exception → wrapped in `EmbeddingError` and re-raised


### ADR-007 — StorageBackend ABC for file storage

**Decision:** Abstract file storage behind a `StorageBackend` interface (`save`, `load`, `delete`, `exists`) with `LocalStorageBackend` as the initial implementation.

**Rationale:**
- Calling code in routers and ingestion service is completely agnostic to the storage medium.
- Swapping to S3 / Azure Blob only requires writing a new class and changing the `get_storage()` dependency — zero changes to routers or the ingestion pipeline.
- `storage_path` is stored in the `documents` row so the path is opaque to callers (works for both local paths and S3 object keys).

---

### ADR-008 — FastAPI BackgroundTasks for ingestion (not Celery/RQ)

**Decision:** Use FastAPI's built-in `BackgroundTasks` to run the ingestion pipeline immediately after the upload response is returned.

**Rationale:**
- Zero additional infrastructure — no queue broker, no worker processes.
- Sufficient for single-node, low-throughput ingestion (< ~10 concurrent uploads).

**When to reconsider:** If ingestion volume grows, the pipeline should be moved to Celery (with Redis as broker) or RQ. Concrete triggers: p99 ingestion time > 30 s, worker memory exceeding container limits, or a need for retries/dead-letter queues. The `_run_pipeline()` function is already extracted from any FastAPI context so it requires zero changes to migrate.

---

### ADR-009 — SHA-256 content hash for deduplication

**Decision:** Compute a SHA-256 hex digest of the raw file bytes and store it in `documents.content_hash`. On upload, check `(user_id, content_hash)` uniqueness before storing.

**Rationale:**
- Prevents the same file from being ingested and embedded twice (idempotent uploads).
- Hash is computed before writing to storage — no wasted disk I/O on duplicates.
- Per-user scope: two users can upload the same file and each gets their own document row.

---

### ADR-010 — unstructured for document parsing

**Decision:** Use the `unstructured` library for text extraction from PDF, DOCX, TXT, MD, and HTML.

**Rationale:**
- Single API (`partition(filename=...)`) handles all supported formats with automatic format detection.
- Emits structured `Element` objects with page numbers, making metadata extraction straightforward.

**Trade-off:** `unstructured` is a heavy dependency (100 MB+ with optional extras). Full PDF support requires system packages (`poppler-utils`, `libmagic`). The Docker image build installs these; local Windows dev only has TXT/MD/HTML support without additional setup.


**Decision:** Use ESLint 9 with the new flat config (`eslint.config.js`) rather than the legacy `.eslintrc.cjs`.

**Rationale:**
- ESLint 9 is the current major release; the legacy format is deprecated.
- `eslint-plugin-react-hooks@5` requires ESLint 9.
- Flat config is more explicit and composable with no implicit rule cascading.

---

## ADR-020: SSE over WebSocket for streaming chat responses

**Decision:** Use Server-Sent Events (SSE) for streaming chat responses.

**Rationale:**
- Generation is inherently unidirectional (server streams tokens to client).
- SSE uses plain HTTP; no upgrade handshake required � works transparently
  through any standard HTTP proxy or load balancer.
- FastAPI's StreamingResponse handles SSE natively with 	ext/event-stream.
- WebSocket is overkill when the client never needs to send data mid-stream.

**Trade-off:** If multi-turn "interrupt" semantics are ever needed (client
sends a cancellation signal while streaming), SSE requires a separate DELETE
request to cancel. A WebSocket would be simpler then.

---

## ADR-021: Partial-save strategy for interrupted streams

**Decision:** When an SSE stream is interrupted mid-response (network error,
provider timeout, etc.), save the partial response with a [STREAM_INTERRUPTED]
suffix rather than discarding it.

**Rationale:**
- Users see what was actually generated � better UX than a silent blank entry.
- The session history remains coherent for future turns.
- The assistant message is always closed (no "stuck in generating" state).
- Clear visual marker distinguishes complete from interrupted responses.

**Alternative considered:** Discard partial responses entirely (write nothing to
DB on failure). Simpler invariant but worse UX and harder to debug.

---

## ADR-022: Streaming session opens its own DB session

**Decision:** The SSE event generator opens a fresh AsyncSession via
get_streaming_session() (a context-manager in database.py) rather than
using the FastAPI request-scoped get_db dependency.

**Rationale:** FastAPI's StreamingResponse body is consumed *after* the
route handler returns. If the handler yields the request-scoped session via
get_db, that session is closed (and rolled back) before the generator runs.
get_streaming_session() is explicitly designed for this pattern.

---

## ADR-023: rom __future__ import annotations + FastAPI 0.115.5 incompatibility

**Issue:** FastAPI 0.115.5 introduced a strict check: endpoints with
status_code=204 must have esponse_model=None. When rom __future__ import
annotations is active, Python stores -> None as the string 'None'. FastAPI
evaluates this string via ForwardRef, which returns NoneType (the class) �
truthy � causing the assertion to fire.

**Fix:** Add esponse_model=None explicitly to all endpoints with
status_code=HTTP_204_NO_CONTENT. This explicitly signals "no response model"
regardless of the return annotation.
