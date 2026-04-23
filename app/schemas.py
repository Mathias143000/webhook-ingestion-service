from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class WebhookIn(BaseModel):
    source: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=128)
    payload: Dict[str, Any]


class WebhookAccepted(BaseModel):
    status: str = "accepted"
    event_id: uuid.UUID
    delivery_id: str | None = None


class HealthOut(BaseModel):
    status: str = "ok"
    database: str = "ok"
    queue: str = "disabled"
    queue_depth: int | None = None
    queue_backend: str = "inline"
    version: str = "1.2.0"


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    delivery_id: str | None = None
    request_id: str | None = None
    source: str
    event_type: str
    payload: Dict[str, Any]
    received_at: datetime
    processing_status: str
    processing_attempts: int
    processed_at: datetime | None = None
    error_message: str | None = None


class EventsListOut(BaseModel):
    items: list[EventOut]
    limit: int
    offset: int


class EventsSummaryOut(BaseModel):
    total: int
    pending: int
    processed: int
    failed: int
    queue_depth: int | None = None
    retry_depth: int | None = None
    dead_letter_depth: int | None = None
    by_source: dict[str, int]


class RetryAccepted(BaseModel):
    status: str = "retry_scheduled"
    event_id: uuid.UUID


class QueueStatsOut(BaseModel):
    backend: str
    enabled: bool
    queue_name: str | None = None
    depth: int | None = None
    retry_queue_name: str | None = None
    retry_depth: int | None = None
    dead_letter_queue_name: str | None = None
    dead_letter_depth: int | None = None


class DLQRedriveOut(BaseModel):
    status: str = "redrive_scheduled"
    redriven_count: int
    event_ids: list[uuid.UUID]
