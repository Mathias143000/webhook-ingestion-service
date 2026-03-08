from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from .config import settings
from .db import dispose_db, init_db, ping_db
from .logging_config import get_logger, setup_logging
from .models import Base
from .queue import (
    QueueUnavailableError,
    dispose_queue,
    get_queue_depth,
    is_queue_enabled,
    ping_queue,
)
from .routers.webhooks import router as webhooks_router
from .schemas import HealthOut

logger = get_logger(__name__)
APP_VERSION = "1.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting %s", settings.app_name)

    if settings.auto_create_tables:
        await init_db(Base.metadata)

    yield

    logger.info("Shutting down %s", settings.app_name)
    await dispose_queue()
    await dispose_db()


app = FastAPI(
    title="Webhook Receiver",
    version=APP_VERSION,
    description="Async webhook receiver service (FastAPI + async SQLAlchemy + Postgres).",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    logger.info("HTTP %s %s | request_id=%s", request.method, request.url.path, request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "HTTP %s %s -> %s | request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
        )
        return response
    except Exception:
        logger.exception(
            "Unhandled error on %s %s | request_id=%s", request.method, request.url.path, request_id
        )
        raise


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    db_ok = await ping_db()
    queue_ok = await ping_queue()
    queue_enabled = is_queue_enabled()
    queue_status = "disabled"
    queue_depth = None

    if queue_enabled:
        queue_status = "ok" if queue_ok else "unavailable"
        if queue_ok:
            try:
                queue_depth = await get_queue_depth()
            except QueueUnavailableError:
                queue_ok = False
                queue_status = "unavailable"

    if not db_ok or (queue_enabled and not queue_ok):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependency unavailable",
        )
    return HealthOut(
        status="ok",
        database="ok",
        queue=queue_status,
        queue_depth=queue_depth,
        queue_backend=settings.task_queue_backend,
        version=APP_VERSION,
    )


app.include_router(webhooks_router)
