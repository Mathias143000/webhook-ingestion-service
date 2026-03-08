from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Event


async def create_event(
    session: AsyncSession,
    *,
    delivery_id: str | None,
    source: str,
    event_type: str,
    payload: dict,
) -> Event:
    event = Event(
        delivery_id=delivery_id,
        source=source,
        event_type=event_type,
        payload=payload,
        processing_status=Event.ProcessingStatus.PENDING,
        processing_attempts=0,
    )
    session.add(event)
    try:
        await session.commit()
        await session.refresh(event)
    except Exception:
        await session.rollback()
        raise
    return event


async def list_events(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    source: Optional[str] = None,
) -> list[Event]:
    stmt = select(Event).order_by(Event.received_at.desc()).limit(limit).offset(offset)
    if source:
        stmt = stmt.where(Event.source == source)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_event_by_delivery_id(session: AsyncSession, *, delivery_id: str) -> Event | None:
    stmt = select(Event).where(Event.delivery_id == delivery_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_event_by_id(session: AsyncSession, *, event_id) -> Event | None:
    stmt = select(Event).where(Event.id == event_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_events_summary(session: AsyncSession) -> dict[str, object]:
    total = await session.scalar(select(func.count()).select_from(Event))
    status_rows = await session.execute(
        select(Event.processing_status, func.count())
        .group_by(Event.processing_status)
        .order_by(Event.processing_status)
    )
    source_rows = await session.execute(
        select(Event.source, func.count()).group_by(Event.source).order_by(Event.source)
    )
    status_counts = {status: count for status, count in status_rows.all()}
    source_counts = {source: count for source, count in source_rows.all()}

    return {
        "total": total or 0,
        "pending": status_counts.get(Event.ProcessingStatus.PENDING, 0),
        "processed": status_counts.get(Event.ProcessingStatus.PROCESSED, 0),
        "failed": status_counts.get(Event.ProcessingStatus.FAILED, 0),
        "by_source": source_counts,
    }
