from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AsyncSessionLocal
from ..logging_config import get_logger
from ..models import Event

logger = get_logger(__name__)


async def process_event(session: AsyncSession, event: Event) -> None:
    """Async placeholder processor with explicit lifecycle states."""
    event.processing_attempts += 1
    try:
        await asyncio.sleep(0)

        if event.payload.get("force_failure") is True:
            raise ValueError("Synthetic processing failure requested by payload")

        event.processing_status = Event.ProcessingStatus.PROCESSED
        event.processed_at = datetime.now(timezone.utc)
        event.error_message = None
        await session.commit()
        logger.info("Event processed: %s", str(event.id))
    except Exception as exc:
        event.processing_status = Event.ProcessingStatus.FAILED
        event.processed_at = None
        event.error_message = str(exc)
        await session.commit()
        logger.exception("Failed to process event: %s", str(event.id))


async def process_event_by_id(event_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        obj = await session.get(Event, event_id)
        if not obj:
            logger.warning("Event not found for processing: %s", str(event_id))
            return
        await process_event(session, obj)
