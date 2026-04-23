from __future__ import annotations

import hmac
import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import settings
from ..db import get_session
from ..logging_config import get_logger
from ..metrics import record_duplicate, record_webhook_intake
from ..queue import (
    QueueUnavailableError,
    enqueue_event,
    get_queue_snapshot,
    is_queue_enabled,
    redrive_dead_letter,
)
from ..schemas import (
    DLQRedriveOut,
    EventsListOut,
    EventsSummaryOut,
    QueueStatsOut,
    RetryAccepted,
    WebhookAccepted,
    WebhookIn,
)
from ..security import verify_webhook_signature
from ..services.processor import process_event_by_id

logger = get_logger(__name__)
router = APIRouter(tags=["webhooks"])


async def _get_queue_depth_or_none() -> int | None:
    try:
        snapshot = await get_queue_snapshot()
        return snapshot.main_depth
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Queue unavailable",
        ) from exc


async def _get_queue_snapshot_or_raise():
    try:
        return await get_queue_snapshot()
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Queue unavailable",
        ) from exc


async def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-KEY"),
) -> None:
    if not settings.api_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@router.post(
    "/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookAccepted,
    dependencies=[Depends(require_api_key)],
)
async def receive_webhook(
    data: WebhookIn,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> WebhookAccepted:
    body = await request.body()
    delivery_id = request.headers.get(settings.webhook_id_header)
    timestamp = request.headers.get(settings.webhook_timestamp_header)
    signature = request.headers.get(settings.webhook_signature_header)
    verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        signature=signature,
    )

    logger.info(
        "Webhook received | source=%s event_type=%s | client=%s",
        data.source,
        data.event_type,
        request.client.host if request.client else "unknown",
    )

    if delivery_id:
        existing = await crud.get_event_by_delivery_id(session, delivery_id=delivery_id)
        if existing is not None:
            logger.info(
                "Duplicate delivery ignored | delivery_id=%s event_id=%s",
                delivery_id,
                str(existing.id),
            )
            record_duplicate()
            record_webhook_intake(data.source, "duplicate")
            return WebhookAccepted(
                status="duplicate",
                event_id=existing.id,
                delivery_id=existing.delivery_id,
            )

    event = await crud.create_event(
        session,
        delivery_id=delivery_id,
        request_id=getattr(request.state, "request_id", None),
        source=data.source,
        event_type=data.event_type,
        payload=data.payload,
    )
    if is_queue_enabled():
        try:
            await enqueue_event(event.id)
        except QueueUnavailableError as exc:
            logger.exception("Failed to enqueue event | event_id=%s", event.id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Queue unavailable",
            ) from exc
    else:
        background_tasks.add_task(process_event_by_id, event.id, final_attempt=True)
    record_webhook_intake(data.source, "accepted")
    return WebhookAccepted(
        status="accepted",
        event_id=event.id,
        delivery_id=event.delivery_id,
    )


@router.get(
    "/events",
    response_model=EventsListOut,
    dependencies=[Depends(require_api_key)],
)
async def get_events(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: Optional[str] = Query(default=None, min_length=1, max_length=128),
    session: AsyncSession = Depends(get_session),
) -> EventsListOut:
    items = await crud.list_events(session, limit=limit, offset=offset, source=source)
    return EventsListOut(items=items, limit=limit, offset=offset)


@router.get(
    "/events/summary",
    response_model=EventsSummaryOut,
    dependencies=[Depends(require_api_key)],
)
async def get_events_summary(session: AsyncSession = Depends(get_session)) -> EventsSummaryOut:
    summary = await crud.get_events_summary(session)
    snapshot = await _get_queue_snapshot_or_raise()
    summary["queue_depth"] = snapshot.main_depth
    summary["retry_depth"] = snapshot.retry_depth
    summary["dead_letter_depth"] = snapshot.dead_letter_depth
    return EventsSummaryOut(**summary)


@router.get(
    "/queue/stats",
    response_model=QueueStatsOut,
    dependencies=[Depends(require_api_key)],
)
async def get_queue_stats() -> QueueStatsOut:
    snapshot = await _get_queue_snapshot_or_raise()
    return QueueStatsOut(
        backend=settings.task_queue_backend,
        enabled=is_queue_enabled(),
        queue_name=settings.event_queue_name if is_queue_enabled() else None,
        depth=snapshot.main_depth,
        retry_queue_name=(
            settings.retry_queue_name if settings.task_queue_backend == "rabbitmq" else None
        ),
        retry_depth=snapshot.retry_depth,
        dead_letter_queue_name=(
            settings.dead_letter_queue_name if settings.task_queue_backend == "rabbitmq" else None
        ),
        dead_letter_depth=snapshot.dead_letter_depth,
    )


@router.post(
    "/events/{event_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RetryAccepted,
    dependencies=[Depends(require_api_key)],
)
async def retry_event(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> RetryAccepted:
    event = await crud.get_event_by_id(session, event_id=event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    if event.processing_status == event.ProcessingStatus.PROCESSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Processed event cannot be retried",
        )

    if is_queue_enabled():
        try:
            await enqueue_event(event.id)
        except QueueUnavailableError as exc:
            logger.exception("Failed to enqueue retry | event_id=%s", event.id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Queue unavailable",
            ) from exc
    else:
        background_tasks.add_task(process_event_by_id, event.id, final_attempt=True)
    return RetryAccepted(event_id=event.id)


@router.post(
    "/queue/dlq/redrive",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DLQRedriveOut,
    dependencies=[Depends(require_api_key)],
)
async def redrive_dlq(
    limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> DLQRedriveOut:
    redriven = await redrive_dead_letter(limit=limit)
    await crud.mark_events_pending(session, event_ids=redriven)
    return DLQRedriveOut(redriven_count=len(redriven), event_ids=redriven)
