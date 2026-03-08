from __future__ import annotations

import asyncio

from .config import settings
from .db import dispose_db
from .logging_config import get_logger, setup_logging
from .queue import dequeue_event, dispose_queue, is_queue_enabled
from .services.processor import process_event_by_id

logger = get_logger(__name__)


async def run_worker() -> None:
    if not is_queue_enabled():
        raise RuntimeError("Worker requires TASK_QUEUE_BACKEND=redis")

    logger.info("Worker started | queue=%s", settings.event_queue_name)
    while True:
        event_id = await dequeue_event(timeout_seconds=settings.worker_poll_timeout_seconds)
        if event_id is None:
            continue
        logger.info("Worker picked event | event_id=%s", event_id)
        await process_event_by_id(event_id)


async def _main() -> None:
    setup_logging()
    try:
        await run_worker()
    finally:
        await dispose_queue()
        await dispose_db()


if __name__ == "__main__":
    asyncio.run(_main())
