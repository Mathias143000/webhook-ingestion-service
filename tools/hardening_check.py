from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def require_markers(errors: list[str], path: Path, markers: list[str]) -> None:
    text = read(path)
    for marker in markers:
        if marker not in text:
            fail(errors, f"{path.relative_to(ROOT)} is missing marker: {marker}")


def main() -> int:
    errors: list[str] = []

    require_markers(
        errors,
        ROOT / "Dockerfile",
        [
            "adduser --disabled-password",
            "USER appuser",
            "HEALTHCHECK",
        ],
    )

    require_markers(
        errors,
        ROOT / ".github" / "workflows" / "ci.yml",
        [
            "Hardening policy check",
            "tools/hardening_check.py",
            "python -m ruff check app tests tools",
            "python -m pytest -q",
            "docker compose config",
            "tools/smoke_check.py",
            "tools/collect_logs.py",
        ],
    )

    require_markers(
        errors,
        ROOT / "docker-compose.yml",
        [
            "nginx:1.27-alpine",
            "rabbitmq:3.13-management-alpine",
            "RETRY_QUEUE_NAME",
            "DEAD_LETTER_QUEUE_NAME",
            "RABBITMQ_MAX_DELIVERY_ATTEMPTS",
            "prom/prometheus",
            "prom/alertmanager",
            "grafana/grafana-oss",
            "otel/opentelemetry-collector-contrib",
            "grafana/tempo",
            "healthcheck:",
        ],
    )

    for required in [
        ROOT / "nginx" / "default.conf",
        ROOT / "prometheus.yml",
        ROOT / "alerts.yml",
        ROOT / "alertmanager.yml",
        ROOT / "rabbitmq" / "enabled_plugins",
        ROOT / "otel-collector" / "config.yml",
        ROOT / "tempo" / "config.yml",
        ROOT / "tools" / "smoke_check.py",
        ROOT / "tools" / "send_signed_webhook.py",
        ROOT / "tools" / "redrive_dlq.py",
        ROOT / "tools" / "collect_logs.py",
        ROOT / "docs" / "hardening.md",
    ]:
        if not required.exists():
            fail(errors, f"missing required hardening asset: {required.relative_to(ROOT)}")

    require_markers(
        errors,
        ROOT / "README.md",
        [
            "`RabbitMQ` with main queue, retry queue, and dead-letter queue",
            "DLQ redrive",
            "hardening policy check",
            "docs/hardening.md",
            "compose-smoke",
        ],
    )

    require_markers(
        errors,
        ROOT / "app" / "routers" / "webhooks.py",
        [
            "redrive_dead_letter",
            "/queue/dlq/redrive",
        ],
    )

    report = {
        "status": "failed" if errors else "passed",
        "checks": [
            "application image runs as non-root",
            "CI includes event workload hardening policy and compose smoke",
            "RabbitMQ retry/DLQ/redrive assets are present",
            "compose stack includes edge, async, observability, and health checks",
            "operator tools and hardening docs are present",
        ],
        "errors": errors,
    }

    output_dir = ROOT / "artifacts" / "hardening"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "hardening-report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Webhook workload hardening checks passed.")
    print(f"Report: {output_dir / 'hardening-report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
