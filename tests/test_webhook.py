import hashlib
import hmac
import json
import time

import pytest

import app.routers.webhooks as webhooks_module
from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Event

VALID_PAYLOAD = {
    "source": "telegram_bot",
    "event_type": "user_registered",
    "payload": {"user_id": 123, "username": "john_doe"},
}


def make_signature(secret: str, payload: dict, timestamp: int) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return body, digest


@pytest.mark.asyncio
async def test_webhook_accepts_valid_payload(client):
    r = await client.post("/webhook", json=VALID_PAYLOAD)
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"
    assert "event_id" in r.json()
    assert "X-Request-ID" in r.headers


@pytest.mark.asyncio
async def test_webhook_enqueues_event_when_redis_queue_backend_enabled(client, monkeypatch):
    captured = {}

    async def _enqueue(event_id):
        captured["event_id"] = str(event_id)

    monkeypatch.setattr(webhooks_module, "is_queue_enabled", lambda: True)
    monkeypatch.setattr(webhooks_module, "enqueue_event", _enqueue)

    r = await client.post("/webhook", json=VALID_PAYLOAD)
    assert r.status_code == 202
    assert captured["event_id"] == r.json()["event_id"]


@pytest.mark.asyncio
async def test_webhook_returns_422_on_invalid_payload(client):
    invalid = {"source": "x", "payload": {"a": 1}}
    r = await client.post("/webhook", json=invalid)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_event_saved_to_db(client):
    await client.post("/webhook", json=VALID_PAYLOAD)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(Event.__table__.select())).fetchall()
        assert len(rows) >= 1


@pytest.mark.asyncio
async def test_get_events_returns_list(client):
    await client.post("/webhook", json=VALID_PAYLOAD)
    r = await client.get("/events?limit=10&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["items"], list)
    assert data["limit"] == 10
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_events_filter_by_source(client):
    await client.post("/webhook", json=VALID_PAYLOAD)
    await client.post("/webhook", json={**VALID_PAYLOAD, "source": "stripe"})

    r = await client.get("/events?source=telegram_bot")
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["source"] == "telegram_bot" for i in items)


@pytest.mark.asyncio
async def test_get_events_limit_out_of_range_returns_422(client):
    r = await client.get("/events?limit=101")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_api_key_protection_requires_header(client):
    old = settings.api_key
    settings.api_key = "supersecret"
    try:
        r = await client.post("/webhook", json=VALID_PAYLOAD)
        assert r.status_code == 401
    finally:
        settings.api_key = old


@pytest.mark.asyncio
async def test_api_key_protection_allows_valid_key(client):
    old = settings.api_key
    settings.api_key = "supersecret"
    try:
        r = await client.post("/webhook", json=VALID_PAYLOAD, headers={"X-API-KEY": "supersecret"})
        assert r.status_code == 202
    finally:
        settings.api_key = old


@pytest.mark.asyncio
async def test_duplicate_delivery_id_is_idempotent(client):
    headers = {"X-Webhook-ID": "delivery-1"}

    first = await client.post("/webhook", json=VALID_PAYLOAD, headers=headers)
    second = await client.post("/webhook", json=VALID_PAYLOAD, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["status"] == "duplicate"
    assert second.json()["event_id"] == first.json()["event_id"]

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(Event.__table__.select())).fetchall()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_webhook_signature_validation_rejects_invalid_signature(client):
    old_secret = settings.webhook_secret
    settings.webhook_secret = "topsecret"
    try:
        timestamp = int(time.time())
        body, _signature = make_signature(settings.webhook_secret, VALID_PAYLOAD, timestamp)
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Timestamp": str(timestamp),
                "X-Webhook-Signature": "invalid",
            },
        )
        assert response.status_code == 401
    finally:
        settings.webhook_secret = old_secret


@pytest.mark.asyncio
async def test_webhook_signature_validation_accepts_valid_signature(client):
    old_secret = settings.webhook_secret
    settings.webhook_secret = "topsecret"
    try:
        timestamp = int(time.time())
        body, signature = make_signature(settings.webhook_secret, VALID_PAYLOAD, timestamp)
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Timestamp": str(timestamp),
                "X-Webhook-Signature": signature,
            },
        )
        assert response.status_code == 202
    finally:
        settings.webhook_secret = old_secret


@pytest.mark.asyncio
async def test_event_failure_and_retry_flow(client):
    payload = {
        "source": "stripe",
        "event_type": "payment_failed",
        "payload": {"force_failure": True},
    }
    response = await client.post(
        "/webhook", json=payload, headers={"X-Webhook-ID": "delivery-fail"}
    )
    assert response.status_code == 202
    event_id = response.json()["event_id"]

    summary = await client.get("/events/summary")
    assert summary.status_code == 200
    assert summary.json()["failed"] == 1

    retry = await client.post(f"/events/{event_id}/retry")
    assert retry.status_code == 202
    assert retry.json()["status"] == "retry_scheduled"

    summary = await client.get("/events/summary")
    assert summary.status_code == 200
    assert summary.json()["failed"] == 1


@pytest.mark.asyncio
async def test_events_summary_returns_aggregates(client):
    await client.post("/webhook", json=VALID_PAYLOAD, headers={"X-Webhook-ID": "delivery-a"})
    await client.post(
        "/webhook",
        json={"source": "stripe", "event_type": "charge.succeeded", "payload": {"amount": 100}},
        headers={"X-Webhook-ID": "delivery-b"},
    )

    response = await client.get("/events/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["processed"] == 2
    assert payload["failed"] == 0
    assert payload["queue_depth"] is None
    assert payload["by_source"] == {"stripe": 1, "telegram_bot": 1}


@pytest.mark.asyncio
async def test_queue_stats_returns_disabled_in_inline_mode(client):
    response = await client.get("/queue/stats")
    assert response.status_code == 200
    assert response.json() == {
        "backend": "inline",
        "enabled": False,
        "queue_name": None,
        "depth": None,
    }


@pytest.mark.asyncio
async def test_queue_stats_returns_depth_when_redis_backend_enabled(client, monkeypatch):
    old_backend = settings.task_queue_backend
    settings.task_queue_backend = "redis"
    monkeypatch.setattr(webhooks_module, "is_queue_enabled", lambda: True)

    async def _depth():
        return 3

    monkeypatch.setattr(webhooks_module, "_get_queue_depth_or_none", _depth)

    try:
        response = await client.get("/queue/stats")
        assert response.status_code == 200
        assert response.json() == {
            "backend": "redis",
            "enabled": True,
            "queue_name": settings.event_queue_name,
            "depth": 3,
        }
    finally:
        settings.task_queue_backend = old_backend
