import pytest

import app.main as main_module


@pytest.mark.asyncio
async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "database": "ok",
        "queue": "disabled",
        "queue_depth": None,
        "queue_backend": "inline",
        "version": "2.0.0",
    }


@pytest.mark.asyncio
async def test_health_returns_503_when_db_unavailable(client, monkeypatch):
    async def _broken_ping() -> bool:
        return False

    monkeypatch.setattr(main_module, "ping_db", _broken_ping)

    r = await client.get("/health")
    assert r.status_code == 503
    assert r.json()["detail"] == "Dependency unavailable"


@pytest.mark.asyncio
async def test_health_returns_503_when_queue_is_unavailable(client, monkeypatch):
    async def _ok_ping() -> bool:
        return True

    async def _broken_queue_ping() -> bool:
        return False

    monkeypatch.setattr(main_module, "ping_db", _ok_ping)
    monkeypatch.setattr(main_module, "is_queue_enabled", lambda: True)
    monkeypatch.setattr(main_module, "ping_queue", _broken_queue_ping)

    r = await client.get("/health")
    assert r.status_code == 503
    assert r.json()["detail"] == "Dependency unavailable"
