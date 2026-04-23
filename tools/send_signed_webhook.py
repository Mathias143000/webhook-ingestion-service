from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.request
from typing import Any


def build_signature(secret: str, body: bytes, timestamp: int) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def send_webhook(
    *,
    base_url: str,
    secret: str,
    api_key: str,
    payload: dict[str, Any],
    delivery_id: str,
) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/webhook",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
            "X-Webhook-ID": delivery_id,
            "X-Webhook-Timestamp": str(timestamp),
            "X-Webhook-Signature": build_signature(secret, body, timestamp),
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18180")
    parser.add_argument("--secret", default="topsecret")
    parser.add_argument("--api-key", default="supersecret")
    parser.add_argument("--delivery-id", required=True)
    parser.add_argument("--payload-json", required=True)
    args = parser.parse_args()

    payload = json.loads(args.payload_json)
    result = send_webhook(
        base_url=args.base_url,
        secret=args.secret,
        api_key=args.api_key,
        payload=payload,
        delivery_id=args.delivery_id,
    )
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
