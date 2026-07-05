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
