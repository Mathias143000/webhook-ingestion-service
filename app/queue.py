from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from .config import settings
from .logging_config import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis


class QueueUnavailableError(RuntimeError):
    pass


_redis_client: "Redis | None" = None


def is_queue_enabled() -> bool:
    return settings.task_queue_backend == "redis"


def _get_queue_client() -> "Redis":
    global _redis_client
    if not is_queue_enabled():
        raise QueueUnavailableError("Redis queue is disabled")
    if _redis_client is None:
        try:
            from redis.asyncio import Redis
        except ModuleNotFoundError as exc:
            raise QueueUnavailableError(
                "Redis dependency is not installed. Run pip install -r requirements.txt"
            ) from exc
        _redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


async def dispose_queue() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def ping_queue() -> bool | None:
    if not is_queue_enabled():
        return None
    try:
        client = _get_queue_client()
        return bool(await client.ping())
    except Exception:
        logger.exception("Queue ping failed")
        return False


async def get_queue_depth() -> int | None:
    if not is_queue_enabled():
        return None
    try:
        client = _get_queue_client()
        return int(await client.llen(settings.event_queue_name))
    except Exception as exc:
        raise QueueUnavailableError("Failed to read queue depth") from exc


async def enqueue_event(event_id: uuid.UUID) -> None:
    try:
        client = _get_queue_client()
        await client.rpush(settings.event_queue_name, str(event_id))
    except Exception as exc:
        raise QueueUnavailableError("Failed to enqueue event") from exc


async def dequeue_event(*, timeout_seconds: int) -> uuid.UUID | None:
    client = _get_queue_client()
    payload = await client.blpop(settings.event_queue_name, timeout=timeout_seconds)
    if payload is None:
        return None

    _queue_name, event_id = payload
    try:
        return uuid.UUID(event_id)
    except ValueError:
        logger.warning("Skipping invalid event id from queue: %s", event_id)
        return None
