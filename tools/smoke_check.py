from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from send_signed_webhook import send_webhook


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    body = None
    request_headers = headers or {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json", **request_headers}

    request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.getcode()
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        content = exc.read().decode("utf-8")

    if status != expected_status:
        raise RuntimeError(f"{url} returned {status}, expected {expected_status}: {content}")

    return json.loads(content) if content else {}


def request_ok(url: str) -> None:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.getcode() != 200:
            raise RuntimeError(f"{url} returned {response.getcode()} instead of 200")


def wait_for(predicate, *, timeout: int, step: float, description: str):
    started = time.time()
    while time.time() - started < timeout:
        result = predicate()
        if result:
            return result
        time.sleep(step)
    raise RuntimeError(f"Timed out waiting for {description}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18180")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:19190")
    parser.add_argument("--alertmanager-url", default="http://127.0.0.1:19193")
    parser.add_argument("--grafana-url", default="http://127.0.0.1:13150")
    parser.add_argument("--tempo-url", default="http://127.0.0.1:13221")
    parser.add_argument("--api-key", default="supersecret")
    parser.add_argument("--secret", default="topsecret")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    auth_headers = {"X-API-KEY": args.api_key}
    run_id = str(int(time.time()))
    accepted_delivery_id = f"smoke-accepted-{run_id}"
    retryable_delivery_id = f"smoke-retryable-{run_id}"

    health = request_json(f"{base_url}/health")
    if health["status"] != "ok":
        raise RuntimeError(f"Health check failed: {health}")

    accepted = send_webhook(
        base_url=base_url,
        secret=args.secret,
        api_key=args.api_key,
        payload={
            "source": "smoke",
            "event_type": "demo.accepted",
            "payload": {"kind": "accepted"},
        },
        delivery_id=accepted_delivery_id,
    )
    if accepted["status"] != "accepted":
        raise RuntimeError(f"Expected accepted webhook, got {accepted}")

    duplicate = send_webhook(
        base_url=base_url,
        secret=args.secret,
        api_key=args.api_key,
        payload={
            "source": "smoke",
            "event_type": "demo.accepted",
            "payload": {"kind": "accepted"},
        },
        delivery_id=accepted_delivery_id,
    )
    if duplicate["status"] != "duplicate":
        raise RuntimeError(f"Expected duplicate webhook, got {duplicate}")

    request_json(
        f"{base_url}/webhook",
        method="POST",
        headers={
            "X-API-KEY": args.api_key,
            "X-Webhook-ID": "smoke-invalid-signature",
            "X-Webhook-Timestamp": str(int(time.time())),
            "X-Webhook-Signature": "invalid",
        },
        payload={
            "source": "smoke",
            "event_type": "demo.invalid",
            "payload": {"kind": "invalid"},
        },
        expected_status=401,
    )

    failed = send_webhook(
        base_url=base_url,
        secret=args.secret,
        api_key=args.api_key,
        payload={
            "source": "smoke",
            "event_type": "demo.retryable",
            "payload": {"fail_attempts_remaining": 3},
        },
        delivery_id=retryable_delivery_id,
    )

    def dlq_ready():
        stats = request_json(f"{base_url}/queue/stats", headers=auth_headers)
        summary = request_json(f"{base_url}/events/summary", headers=auth_headers)
        if (stats.get("dead_letter_depth") or 0) >= 1 and summary.get("failed", 0) >= 1:
            return stats
        return None

    wait_for(dlq_ready, timeout=90, step=2, description="event to reach DLQ")

    redrive = request_json(
        f"{base_url}/queue/dlq/redrive?limit=10",
        method="POST",
        headers=auth_headers,
        expected_status=202,
    )
    if redrive["redriven_count"] < 1:
        raise RuntimeError(f"Expected at least one redriven event, got {redrive}")

    def event_processed():
        events_query = urllib.parse.urlencode({"limit": 20, "offset": 0, "source": "smoke"})
        events = request_json(
            f"{base_url}/events?{events_query}",
            headers=auth_headers,
        )
        for item in events["items"]:
            if item["id"] == failed["event_id"] and item["processing_status"] == "processed":
                stats = request_json(f"{base_url}/queue/stats", headers=auth_headers)
                if (stats.get("dead_letter_depth") or 0) == 0:
                    return True
        return False

    wait_for(
        event_processed,
        timeout=90,
        step=2,
        description="redriven event to process successfully",
    )

    metrics_text = urllib.request.urlopen(f"{base_url}/metrics", timeout=10).read().decode("utf-8")
    if "webhook_intake_total" not in metrics_text:
        raise RuntimeError("Prometheus metrics endpoint does not expose webhook_intake_total")

    request_ok(f"{args.prometheus_url.rstrip('/')}/-/ready")
    request_ok(f"{args.alertmanager_url.rstrip('/')}/-/ready")
    request_json(f"{args.grafana_url.rstrip('/')}/api/health")

    traces = request_json(f"{args.tempo_url.rstrip('/')}/api/search?q={{}}&limit=5")
    if not traces:
        raise RuntimeError("Tempo search did not return any traces")

    print(
        json.dumps(
            {"status": "ok", "message": "Smoke checks completed successfully"},
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
