from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    class ProcessingStatus:
        PENDING = "pending"
        PROCESSED = "processed"
        FAILED = "failed"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )
    source: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processing_status: Mapped[str] = mapped_column(
        String(32),
        default=ProcessingStatus.PENDING,
        index=True,
        nullable=False,
    )
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
