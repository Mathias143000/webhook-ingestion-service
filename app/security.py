from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, status

from .config import settings
from .metrics import record_signature_failure


def verify_webhook_signature(*, body: bytes, timestamp: str | None, signature: str | None) -> None:
    if not settings.webhook_secret:
        return

    if not timestamp or not signature:
        record_signature_failure()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature headers",
        )

    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        record_signature_failure()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook timestamp",
        ) from exc

    now = int(time.time())
    if abs(now - timestamp_value) > settings.webhook_timestamp_tolerance_seconds:
        record_signature_failure()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook timestamp is outside the allowed tolerance window",
        )

    signed_payload = f"{timestamp}.{body.decode('utf-8')}".encode("utf-8")
    expected_signature = hmac.new(
        settings.webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        record_signature_failure()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )
