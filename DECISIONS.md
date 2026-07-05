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

## Part 4: Document Ingestion Pipeline

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
