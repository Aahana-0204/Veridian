from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application --
    app_name: str = "Veridian RAG API"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # -- Database --
    database_url: str
    test_database_url: str = "postgresql+asyncpg://localhost:5432/ragdb_test"

    # -- Redis --
    redis_url: str = "redis://localhost:6379/0"

    # -- Security --
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # -- CORS --
    # Stored as a plain str so pydantic-settings never attempts json.loads() on it.
    # Accepts a comma-separated list or a JSON array string.
    # Parsed to list[str] via the cors_origins_list property used by main.py.
    cors_origins: str = "http://localhost:5173"

    # -- Upload / Storage --
    max_upload_size_mb: int = 50
    upload_dir: str = "/tmp/veridian_uploads"

    # -- Chunking --
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # -- Retrieval --
    top_k: int = 5
    hybrid_search_enabled: bool = True
    # candidate_multiplier: fetch top_k * N before RRF/reranking, then trim
    retrieval_candidate_multiplier: int = 4

    # -- Re-ranking --
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_top_n_multiplier: int = 4

    # -- Generation / LLM --
    llm_provider: str = (
        "ollama"  # "ollama" (free forever, local) | "groq" (free tier) | "openai" (paid)
    )
    llm_model: str = "llama3.2:3b"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    llm_context_window: int = 128_000

    # -- Prompt --
    prompt_template: str = "rag_v1"
    max_context_tokens: int = 4000
    max_history_tokens: int = 1000
    embedding_provider: str = (
        "sentence-transformers"  # free default | "openai" for paid
    )
    # Ollama settings (used when llm_provider="ollama")
    ollama_base_url: str = "http://ollama:11434"  # Docker Compose service name
    # OpenAI settings (used when embedding_provider="openai" or llm_provider="openai")
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    # Groq settings (used when llm_provider="groq") — free at console.groq.com
    groq_api_key: str = ""
    # Dimension of the embedding vectors.  MUST match the pgvector column
    # and the chosen model's output size.
    # sentence-transformers/all-MiniLM-L6-v2 → 384  (free, default)
    # openai/text-embedding-3-small           → 1536 (paid)
    # Change only when running the matching Alembic migration.
    embedding_dimensions: int = 384
    # SentenceTransformers settings (used when embedding_provider="sentence-transformers")
    sentence_transformer_model: str = "all-MiniLM-L6-v2"
    # Rate / cost safety
    embedding_batch_size: int = 100  # max texts per provider API call override
    embedding_max_concurrency: int = 3  # concurrent API calls
    # Retry / back-off
    embedding_max_retries: int = 3
    embedding_retry_base_delay: float = 1.0  # seconds
    embedding_retry_max_delay: float = 60.0  # seconds

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> str:
        """Normalize to a raw string — actual list parsing happens in cors_origins_list."""
        if isinstance(v, list):
            return ",".join(v)
        return v

    @field_validator("upload_dir", mode="after")
    @classmethod
    def ensure_upload_dir(cls, v: str) -> str:
        Path(v).mkdir(parents=True, exist_ok=True)
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton -- import and call get_settings() everywhere."""
    return Settings()
