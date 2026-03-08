from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings


def create_engine() -> AsyncEngine:
    # SQLAlchemy async engine includes pooling.
    # NOTE: SQLite (sqlite+aiosqlite) does NOT support pool_size/max_overflow.
    url = settings.database_url
    url_l = url.lower()

    common_kwargs = {
        "echo": False,
        "pool_pre_ping": True,
        "future": True,
    }

    if "sqlite" in url_l:
        return create_async_engine(url, **common_kwargs)

    return create_async_engine(
        url,
        **common_kwargs,
        pool_size=5,
        max_overflow=10,
    )


engine: AsyncEngine = create_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db(metadata: MetaData) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()


async def ping_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
