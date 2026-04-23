from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from .config import settings
from .db import dispose_db, init_db, ping_db
from .logging_config import get_logger, setup_logging
from .metrics import (
    record_http_request,
    render_metrics,
    set_dependency_state,
)
from .models import Base
from .observability import setup_tracing
from .queue import (
    QueueUnavailableError,
    dispose_queue,
    get_queue_depth,
    get_queue_snapshot,
    is_queue_enabled,
    ping_queue,
)
from .routers.webhooks import router as webhooks_router
from .schemas import HealthOut

logger = get_logger(__name__)
APP_VERSION = "2.0.0"
QUEUE_METRICS_REFRESH_SECONDS = 5


async def _queue_metrics_poller() -> None:
    while True:
        try:
            snapshot = await get_queue_snapshot()
            set_dependency_state("queue", True)
            if snapshot.main_depth is not None:
                logger.info(
                    "Queue snapshot | main=%s retry=%s dlq=%s",
                    snapshot.main_depth,
                    snapshot.retry_depth,
                    snapshot.dead_letter_depth,
                )
        except QueueUnavailableError:
            set_dependency_state("queue", False)
        except Exception:
            logger.exception("Failed to refresh queue metrics")
        await asyncio.sleep(QUEUE_METRICS_REFRESH_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting %s", settings.app_name)
    queue_metrics_task: asyncio.Task | None = None

    if settings.auto_create_tables:
        await init_db(Base.metadata)
    if is_queue_enabled():
        queue_metrics_task = asyncio.create_task(_queue_metrics_poller())

    yield

    logger.info("Shutting down %s", settings.app_name)
    if queue_metrics_task is not None:
        queue_metrics_task.cancel()
        try:
            await queue_metrics_task
        except asyncio.CancelledError:
            pass
    await dispose_queue()
    await dispose_db()


app = FastAPI(
    title="Webhook Receiver",
    version=APP_VERSION,
    description="Async webhook receiver service (FastAPI + async SQLAlchemy + Postgres).",
    lifespan=lifespan,
)

setup_tracing(app)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get(settings.request_id_header) or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    logger.info("HTTP %s %s | request_id=%s", request.method, request.url.path, request_id)
    try:
        response = await call_next(request)
        response.headers[settings.request_id_header] = request_id
        logger.info(
            "HTTP %s %s -> %s | request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
        )
        record_http_request(
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - started,
        )
        return response
    except Exception:
        record_http_request(request.method, request.url.path, 500, time.perf_counter() - started)
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
    set_dependency_state("database", db_ok)
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
    set_dependency_state("queue", queue_ok or not queue_enabled)

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


@app.get("/ready", response_model=HealthOut, tags=["health"])
async def ready() -> HealthOut:
    return await health()


@app.get("/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", tags=["metrics"])
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


app.include_router(webhooks_router)
