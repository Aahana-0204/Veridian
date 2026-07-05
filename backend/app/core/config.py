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
    cors_origins: list[str] = ["http://localhost:5173"]

    # -- Upload / Storage --
    max_upload_size_mb: int = 50
    upload_dir: str = "/tmp/veridian_uploads"

    # -- Chunking --
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # -- Embeddings --
    embedding_provider: str = "openai"  # "openai" | "sentence-transformers"
    # OpenAI settings (used when embedding_provider="openai")
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    # Dimension of the embedding vectors.  MUST match the pgvector column
    # (Vector(1536) from Part 2) and the chosen model's output size.
    # Change only when running a migration to resize the column.
    embedding_dimensions: int = 1536
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
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
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
