# Event Workload Hardening

This repository is the event-driven workload in the platform portfolio, so the third hardening wave focuses on async reliability, failure visibility, and operator replay paths.

## What Is Covered

- application container runs as a non-root user
- webhook ingress uses API key and HMAC signature controls
- RabbitMQ topology includes main, retry, and dead-letter queues
- DLQ redrive is exposed through both API and operator tooling
- compose stack includes edge, API, worker, database, broker, cache, metrics, alerts, traces, and dashboards
- CI runs Ruff, repo-local hardening policy, tests, compose validation, and smoke checks
- failure evidence is collected on compose-smoke failure

## Local Validation

```bash
python -m ruff check app tests tools
python tools/hardening_check.py
python -m pytest -q
docker compose config
python tools/smoke_check.py
```

The hardening check writes a local report to:

```text
artifacts/hardening/hardening-report.json
```

The report is ignored by Git because it is runtime evidence, not source code.

## Deliberate Trade-Offs

- This wave uses RabbitMQ retry/DLQ queues rather than implementing a full transactional outbox.
- Logs are structured and collectible through Docker evidence, but Loki is intentionally deferred to avoid duplicating the observability flagship.
- The smoke flow proves retry/DLQ/redrive behavior at lab scale, not production throughput.

## Remaining Backlog

- transactional outbox/inbox pattern
- Loki log search
- k6 load drills
- explicit broker outage drill with postmortem artifact
