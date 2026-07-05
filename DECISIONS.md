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

### ADR-006 — ESLint 9 flat config

**Decision:** Use ESLint 9 with the new flat config (`eslint.config.js`) rather than the legacy `.eslintrc.cjs`.

**Rationale:**
- ESLint 9 is the current major release; the legacy format is deprecated.
- `eslint-plugin-react-hooks@5` requires ESLint 9.
- Flat config is more explicit and composable with no implicit rule cascading.
