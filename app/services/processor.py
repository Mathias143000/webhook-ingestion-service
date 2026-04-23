from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

from opentelemetry.trace import Status, StatusCode
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AsyncSessionLocal
from ..logging_config import get_logger
from ..metrics import record_processing
from ..models import Event
from ..observability import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


async def process_event(session: AsyncSession, event: Event, *, final_attempt: bool) -> bool:
    """Async placeholder processor with explicit lifecycle states."""
    started = time.perf_counter()
    with tracer.start_as_current_span("process_event") as span:
        span.set_attribute("event.id", str(event.id))
        span.set_attribute("event.source", event.source)
        span.set_attribute("event.type", event.event_type)
        event.processing_attempts += 1
        try:
            await asyncio.sleep(0)

            remaining_failures = int(event.payload.get("fail_attempts_remaining", 0) or 0)
            if remaining_failures > 0:
                updated_payload = dict(event.payload)
                updated_payload["fail_attempts_remaining"] = remaining_failures - 1
                event.payload = updated_payload
                raise ValueError("Synthetic transient processing failure requested by payload")

            if event.payload.get("force_failure") is True:
                raise ValueError("Synthetic processing failure requested by payload")

            event.processing_status = Event.ProcessingStatus.PROCESSED
            event.processed_at = datetime.now(timezone.utc)
            event.error_message = None
            await session.commit()
            record_processing(event.source, "processed", time.perf_counter() - started)
            logger.info("Event processed: %s", str(event.id))
            span.set_status(Status(StatusCode.OK))
            return True
        except Exception as exc:
            event.processing_status = (
                Event.ProcessingStatus.FAILED if final_attempt else Event.ProcessingStatus.PENDING
            )
            event.processed_at = None
            event.error_message = str(exc)
            await session.commit()
            record_processing(
                event.source,
                "failed" if final_attempt else "retry",
                time.perf_counter() - started,
            )
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR))
            logger.exception("Failed to process event: %s", str(event.id))
            return False


async def process_event_by_id(event_id: uuid.UUID, *, final_attempt: bool) -> bool:
    async with AsyncSessionLocal() as session:
        obj = await session.get(Event, event_id)
        if not obj:
            logger.warning("Event not found for processing: %s", str(event_id))
            return True
        return await process_event(session, obj, final_attempt=final_attempt)
