from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

http_requests_total = Counter(
    "webhook_http_requests_total",
    "Total HTTP requests served by the API.",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "webhook_http_request_duration_seconds",
    "Latency of HTTP requests handled by the API.",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
webhook_intake_total = Counter(
    "webhook_intake_total",
    "Webhook intake outcomes.",
    ["source", "status"],
)
webhook_signature_failures_total = Counter(
    "webhook_signature_failures_total",
    "Rejected webhook requests due to signature validation failures.",
)
webhook_duplicate_total = Counter(
    "webhook_duplicate_total",
    "Duplicate webhook deliveries ignored by the API.",
)
webhook_processing_total = Counter(
    "webhook_processing_total",
    "Webhook processing outcomes.",
    ["source", "status"],
)
webhook_processing_duration_seconds = Histogram(
    "webhook_processing_duration_seconds",
    "Webhook processing latency.",
    ["source", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
webhook_retry_total = Counter(
    "webhook_retry_total",
    "How many retry publications were scheduled.",
)
webhook_redrive_total = Counter(
    "webhook_redrive_total",
    "How many events were re-driven from the DLQ.",
)
webhook_queue_depth = Gauge(
    "webhook_queue_depth",
    "Current message count by queue lane.",
    ["queue"],
)
dependency_up = Gauge(
    "webhook_dependency_up",
    "Dependency availability as seen by the API.",
    ["dependency"],
)


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    normalized_path = path or "/"
    http_requests_total.labels(method=method, path=normalized_path, status=str(status_code)).inc()
    http_request_duration_seconds.labels(
        method=method,
        path=normalized_path,
    ).observe(duration_seconds)


def record_webhook_intake(source: str, status: str) -> None:
    webhook_intake_total.labels(source=source or "unknown", status=status).inc()


def record_signature_failure() -> None:
    webhook_signature_failures_total.inc()


def record_duplicate() -> None:
    webhook_duplicate_total.inc()


def record_processing(source: str, status: str, duration_seconds: float) -> None:
    normalized_source = source or "unknown"
    webhook_processing_total.labels(source=normalized_source, status=status).inc()
    webhook_processing_duration_seconds.labels(
        source=normalized_source,
        status=status,
    ).observe(duration_seconds)


def record_retry() -> None:
    webhook_retry_total.inc()


def record_redrive(count: int) -> None:
    if count > 0:
        webhook_redrive_total.inc(count)


def set_queue_depths(
    *,
    main_depth: int | None,
    retry_depth: int | None,
    dead_letter_depth: int | None,
) -> None:
    for name, value in {
        "main": main_depth,
        "retry": retry_depth,
        "dead_letter": dead_letter_depth,
    }.items():
        webhook_queue_depth.labels(queue=name).set(float(value or 0))


def set_dependency_state(name: str, is_up: bool) -> None:
    dependency_up.labels(dependency=name).set(1 if is_up else 0)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
