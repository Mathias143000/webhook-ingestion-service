from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import settings
from .logging_config import get_logger
from .metrics import record_redrive, record_retry, set_queue_depths

logger = get_logger(__name__)

if TYPE_CHECKING:
    from aio_pika.abc import (
        AbstractIncomingMessage,
        AbstractRobustChannel,
        AbstractRobustConnection,
    )
    from redis.asyncio import Redis


class QueueUnavailableError(RuntimeError):
    pass


@dataclass
class QueueEnvelope:
    event_id: uuid.UUID
    attempt: int
    raw_message: "AbstractIncomingMessage | None" = None


@dataclass
class QueueSnapshot:
    main_depth: int | None
    retry_depth: int | None
    dead_letter_depth: int | None


_redis_client: "Redis | None" = None
_rabbitmq_connection: "AbstractRobustConnection | None" = None
_rabbitmq_channel: "AbstractRobustChannel | None" = None
_topology_ready = False


def is_queue_enabled() -> bool:
    return settings.task_queue_backend in {"redis", "rabbitmq"}


def _queue_payload(event_id: uuid.UUID, attempt: int) -> bytes:
    return json.dumps(
        {"event_id": str(event_id), "attempt": attempt},
        ensure_ascii=True,
    ).encode("utf-8")


def _decode_payload(raw_body: bytes) -> tuple[uuid.UUID, int]:
    payload = json.loads(raw_body.decode("utf-8"))
    return uuid.UUID(payload["event_id"]), int(payload.get("attempt", 1))


def _get_queue_client() -> "Redis":
    global _redis_client
    if settings.task_queue_backend != "redis":
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


async def _ensure_rabbitmq_topology() -> "AbstractRobustChannel":
    global _rabbitmq_connection, _rabbitmq_channel, _topology_ready
    if settings.task_queue_backend != "rabbitmq":
        raise QueueUnavailableError("RabbitMQ queue is disabled")

    if _rabbitmq_channel is not None and _topology_ready:
        return _rabbitmq_channel

    try:
        from aio_pika import ExchangeType, connect_robust
    except ModuleNotFoundError as exc:
        raise QueueUnavailableError(
            "RabbitMQ dependency is not installed. Run pip install -r requirements.txt"
        ) from exc

    if _rabbitmq_connection is None:
        _rabbitmq_connection = await connect_robust(settings.rabbitmq_url)
    if _rabbitmq_channel is None:
        _rabbitmq_channel = await _rabbitmq_connection.channel()
        await _rabbitmq_channel.set_qos(prefetch_count=10)

    exchange = await _rabbitmq_channel.declare_exchange(
        settings.rabbitmq_exchange_name,
        ExchangeType.DIRECT,
        durable=True,
    )

    main_queue = await _rabbitmq_channel.declare_queue(settings.event_queue_name, durable=True)
    await main_queue.bind(exchange, routing_key=settings.event_queue_name)

    retry_queue = await _rabbitmq_channel.declare_queue(
        settings.retry_queue_name,
        durable=True,
        arguments={
            "x-message-ttl": settings.rabbitmq_retry_delay_ms,
            "x-dead-letter-exchange": settings.rabbitmq_exchange_name,
            "x-dead-letter-routing-key": settings.event_queue_name,
        },
    )
    await retry_queue.bind(exchange, routing_key=settings.retry_queue_name)

    dead_letter_queue = await _rabbitmq_channel.declare_queue(
        settings.dead_letter_queue_name,
        durable=True,
    )
    await dead_letter_queue.bind(exchange, routing_key=settings.dead_letter_queue_name)

    _topology_ready = True
    return _rabbitmq_channel


async def _publish_to_rabbitmq(event_id: uuid.UUID, *, routing_key: str, attempt: int) -> None:
    from aio_pika import DeliveryMode, Message

    channel = await _ensure_rabbitmq_topology()
    exchange = await channel.get_exchange(settings.rabbitmq_exchange_name)
    await exchange.publish(
        Message(
            body=_queue_payload(event_id, attempt),
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
        ),
        routing_key=routing_key,
    )


async def dispose_queue() -> None:
    global _redis_client, _rabbitmq_channel, _rabbitmq_connection, _topology_ready
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
    if _rabbitmq_channel is not None:
        await _rabbitmq_channel.close()
        _rabbitmq_channel = None
    if _rabbitmq_connection is not None:
        await _rabbitmq_connection.close()
        _rabbitmq_connection = None
    _topology_ready = False


async def ping_queue() -> bool | None:
    if not is_queue_enabled():
        return None
    try:
        if settings.task_queue_backend == "redis":
            client = _get_queue_client()
            result = bool(await client.ping())
        else:
            channel = await _ensure_rabbitmq_topology()
            result = not channel.is_closed
        return result
    except Exception:
        logger.exception("Queue ping failed")
        return False


async def get_queue_snapshot() -> QueueSnapshot:
    if not is_queue_enabled():
        snapshot = QueueSnapshot(main_depth=None, retry_depth=None, dead_letter_depth=None)
        set_queue_depths(
            main_depth=snapshot.main_depth,
            retry_depth=snapshot.retry_depth,
            dead_letter_depth=snapshot.dead_letter_depth,
        )
        return snapshot

    if settings.task_queue_backend == "redis":
        try:
            client = _get_queue_client()
            main_depth = int(await client.llen(settings.event_queue_name))
            snapshot = QueueSnapshot(main_depth=main_depth, retry_depth=0, dead_letter_depth=0)
            set_queue_depths(
                main_depth=snapshot.main_depth,
                retry_depth=snapshot.retry_depth,
                dead_letter_depth=snapshot.dead_letter_depth,
            )
            return snapshot
        except Exception as exc:
            raise QueueUnavailableError("Failed to read Redis queue depth") from exc

    try:
        channel = await _ensure_rabbitmq_topology()
        main_queue = await channel.declare_queue(settings.event_queue_name, passive=True)
        retry_queue = await channel.declare_queue(settings.retry_queue_name, passive=True)
        dead_letter_queue = await channel.declare_queue(
            settings.dead_letter_queue_name,
            passive=True,
        )
        snapshot = QueueSnapshot(
            main_depth=main_queue.declaration_result.message_count,
            retry_depth=retry_queue.declaration_result.message_count,
            dead_letter_depth=dead_letter_queue.declaration_result.message_count,
        )
        set_queue_depths(
            main_depth=snapshot.main_depth,
            retry_depth=snapshot.retry_depth,
            dead_letter_depth=snapshot.dead_letter_depth,
        )
        return snapshot
    except Exception as exc:
        raise QueueUnavailableError("Failed to read RabbitMQ queue depth") from exc


async def get_queue_depth() -> int | None:
    snapshot = await get_queue_snapshot()
    return snapshot.main_depth


async def enqueue_event(event_id: uuid.UUID, *, attempt: int = 1) -> None:
    try:
        if settings.task_queue_backend == "redis":
            client = _get_queue_client()
            await client.rpush(settings.event_queue_name, str(event_id))
        elif settings.task_queue_backend == "rabbitmq":
            await _publish_to_rabbitmq(
                event_id,
                routing_key=settings.event_queue_name,
                attempt=attempt,
            )
        else:
            raise QueueUnavailableError("Queue backend is disabled")
    except Exception as exc:
        raise QueueUnavailableError("Failed to enqueue event") from exc


async def dequeue_event(*, timeout_seconds: int) -> QueueEnvelope | None:
    if settings.task_queue_backend == "redis":
        client = _get_queue_client()
        payload = await client.blpop(settings.event_queue_name, timeout=timeout_seconds)
        if payload is None:
            return None

        _queue_name, event_id = payload
        try:
            return QueueEnvelope(event_id=uuid.UUID(event_id), attempt=1)
        except ValueError:
            logger.warning("Skipping invalid event id from queue: %s", event_id)
            return None

    if settings.task_queue_backend != "rabbitmq":
        return None

    channel = await _ensure_rabbitmq_topology()
    queue = await channel.declare_queue(settings.event_queue_name, passive=True)
    message = await queue.get(timeout=timeout_seconds, fail=False)
    if message is None:
        return None

    try:
        event_id, attempt = _decode_payload(message.body)
    except Exception:
        logger.warning("Dropping malformed RabbitMQ message: %s", message.body)
        await message.ack()
        return None

    return QueueEnvelope(event_id=event_id, attempt=attempt, raw_message=message)


async def complete_event(envelope: QueueEnvelope) -> None:
    if envelope.raw_message is not None:
        await envelope.raw_message.ack()


async def retry_or_dead_letter(envelope: QueueEnvelope) -> str:
    if settings.task_queue_backend == "redis":
        await enqueue_event(envelope.event_id)
        return "retry"

    if envelope.raw_message is None:
        raise QueueUnavailableError("RabbitMQ message context is missing")

    next_attempt = envelope.attempt + 1
    if next_attempt <= settings.rabbitmq_max_delivery_attempts:
        await _publish_to_rabbitmq(
            envelope.event_id,
            routing_key=settings.retry_queue_name,
            attempt=next_attempt,
        )
        record_retry()
        await envelope.raw_message.ack()
        return "retry"

    await _publish_to_rabbitmq(
        envelope.event_id,
        routing_key=settings.dead_letter_queue_name,
        attempt=envelope.attempt,
    )
    await envelope.raw_message.ack()
    return "dead_letter"


async def redrive_dead_letter(*, limit: int) -> list[uuid.UUID]:
    if settings.task_queue_backend != "rabbitmq":
        raise QueueUnavailableError("DLQ redrive requires TASK_QUEUE_BACKEND=rabbitmq")

    channel = await _ensure_rabbitmq_topology()
    dead_letter_queue = await channel.declare_queue(settings.dead_letter_queue_name, passive=True)
    redriven: list[uuid.UUID] = []

    for _ in range(limit):
        message = await dead_letter_queue.get(timeout=1, fail=False)
        if message is None:
            break
        try:
            event_id, _attempt = _decode_payload(message.body)
        except Exception:
            logger.warning("Dropping malformed DLQ message during redrive: %s", message.body)
            await message.ack()
            continue

        await _publish_to_rabbitmq(event_id, routing_key=settings.event_queue_name, attempt=1)
        await message.ack()
        redriven.append(event_id)

    record_redrive(len(redriven))
    return redriven
