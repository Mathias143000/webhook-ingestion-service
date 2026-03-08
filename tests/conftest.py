import os
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

# Use SQLite for tests by default (fast, no external deps).
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("API_KEY", "")
os.environ.setdefault("TASK_QUEUE_BACKEND", "inline")

from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (
    Base,  # noqa: E402
    Event,  # noqa: E402
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_test_db():
    test_db = Path("test.db")
    if test_db.exists():
        test_db.unlink()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    if test_db.exists():
        test_db.unlink()


@pytest_asyncio.fixture()
async def client():
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Event))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
