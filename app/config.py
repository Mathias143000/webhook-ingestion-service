from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Example: postgresql+asyncpg://postgres:postgres@db:5432/webhooks
    database_url: str = Field(default="sqlite+aiosqlite:///./dev.db", alias="DATABASE_URL")

    # Optional API key protection. If empty, disabled.
    api_key: str = Field(default="", alias="API_KEY")

    app_name: str = Field(default="webhook-ingestion-service", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    auto_create_tables: bool = Field(default=True, alias="AUTO_CREATE_TABLES")
    task_queue_backend: str = Field(default="inline", alias="TASK_QUEUE_BACKEND")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    event_queue_name: str = Field(default="webhook-events", alias="EVENT_QUEUE_NAME")
    worker_poll_timeout_seconds: int = Field(default=5, alias="WORKER_POLL_TIMEOUT_SECONDS")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    webhook_signature_header: str = Field(
        default="X-Webhook-Signature",
        alias="WEBHOOK_SIGNATURE_HEADER",
    )
    webhook_timestamp_header: str = Field(
        default="X-Webhook-Timestamp",
        alias="WEBHOOK_TIMESTAMP_HEADER",
    )
    webhook_id_header: str = Field(default="X-Webhook-ID", alias="WEBHOOK_ID_HEADER")
    webhook_timestamp_tolerance_seconds: int = Field(
        default=300,
        alias="WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS",
    )

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("task_queue_backend")
    @classmethod
    def validate_task_queue_backend(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"inline", "redis"}:
            raise ValueError("TASK_QUEUE_BACKEND must be either 'inline' or 'redis'")
        return normalized

    @field_validator("worker_poll_timeout_seconds")
    @classmethod
    def validate_worker_poll_timeout_seconds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("WORKER_POLL_TIMEOUT_SECONDS must be greater than or equal to 1")
        return value


settings = Settings()
