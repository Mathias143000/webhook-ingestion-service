# Webhook Ingestion Service

Production-style event ingestion and reliability stand.

This repository is the event-driven integration showcase in the portfolio. It demonstrates secure webhook intake, asynchronous processing, broker-backed retries and DLQ, operational replay tooling, and a full local observability stack.

## Portfolio Role

This is the event-driven workload showcase in the portfolio.

It is most useful when the discussion moves from generic APIs to:

- queue-backed delivery and retry behavior
- idempotency and signed ingress
- DLQ and replay workflow
- observability around async processing

In the broader portfolio this repository complements `enterprise-onprem-platform-lab` and `k8s-gitops-platform-lab` by serving as a realistic workload with asynchronous failure modes, rather than as a platform story on its own.

## What It Demonstrates

- `nginx` as the edge layer in front of the API
- signed webhook intake with HMAC verification and replay window control
- idempotency by delivery ID
- `FastAPI` API + separate `worker`
- `PostgreSQL` for event metadata and processing history
- `RabbitMQ` with main queue, retry queue, and dead-letter queue
- `Redis` as a support dependency for short-lived state and future extensions
- `Prometheus + Grafana + Alertmanager`
- `OpenTelemetry + Tempo`
- structured JSON logs and propagated request IDs
- CI quality checks plus a real `docker compose` smoke flow

## Runtime Architecture

```text
Webhook sender
     |
     v
[nginx edge]
     |
     v
[FastAPI intake API]
  validate API key
  validate HMAC signature
  enforce idempotency
  persist event metadata
     |
     v
[RabbitMQ main queue] ---> [retry queue] ---> [dead-letter queue]
     |
     v
[worker]
  process event
  update lifecycle status
  emit traces / metrics / logs
     |
     v
[PostgreSQL]

Observability:
Prometheus -> Alertmanager
Grafana -> Prometheus + Tempo
JSON logs -> docker compose logs / evidence bundle
```

## Key Endpoints

- `GET /health`
- `GET /ready`
- `GET /live`
- `GET /metrics`
- `POST /webhook`
- `GET /events`
- `GET /events/summary`
- `GET /queue/stats`
- `POST /events/{event_id}/retry`
- `POST /queue/dlq/redrive`

## Local Ports

- Edge API: `http://127.0.0.1:18180`
- Prometheus: `http://127.0.0.1:19190`
- Alertmanager: `http://127.0.0.1:19193`
- Grafana: `http://127.0.0.1:13150`
- Tempo: `http://127.0.0.1:13221`
- RabbitMQ management: `http://127.0.0.1:15692`

These ports intentionally live in a dedicated local range so the stack can coexist with other demo projects on the same machine.

## Quick Start

```bash
python tools/bootstrap_env.py
docker compose up -d --build
python tools/smoke_check.py
```

If smoke passes, the core happy path, duplicate detection, invalid signature handling, retry flow, DLQ redrive, metrics, traces, and alerting readiness are all confirmed.

## Manual Demo Flow

1. Start the stack:

```bash
python tools/bootstrap_env.py
docker compose up -d --build
```

2. Send a signed webhook:

```bash
python tools/send_signed_webhook.py ^
  --delivery-id demo-accepted-1 ^
  --payload-json "{\"source\":\"demo\",\"event_type\":\"invoice.created\",\"payload\":{\"invoice_id\":101}}"
```

3. Inspect the event list:

```bash
python -c "import urllib.request; req=urllib.request.Request('http://127.0.0.1:18180/events?limit=10&offset=0', headers={'X-API-KEY':'supersecret'}); print(urllib.request.urlopen(req).read().decode())"
```

4. Inspect the queue summary:

```bash
python -c "import urllib.request; req=urllib.request.Request('http://127.0.0.1:18180/events/summary', headers={'X-API-KEY':'supersecret'}); print(urllib.request.urlopen(req).read().decode())"
```

5. Re-drive the DLQ manually when needed:

```bash
python tools/redrive_dlq.py
```

## Observability Story

The project exposes the event lifecycle across metrics, traces, logs, and alerts:

- Prometheus scrapes the API and broker metrics
- Alert rules cover service down, DLQ depth, processing failures, and signature failures
- Alertmanager receives active alerts from Prometheus
- Grafana provisions Prometheus, Alertmanager, and Tempo data sources
- Tempo receives OTLP traces from the API and worker
- logs are emitted as JSON and can be captured through `python tools/collect_logs.py --output-dir artifacts/evidence`

## Validation

Local validation used for the portfolio-ready state:

```bash
python -m ruff check app tests tools
python tools/hardening_check.py
python -m pytest -q
docker compose config
python tools/smoke_check.py
python tools/collect_logs.py --output-dir artifacts/evidence
```

## CI

GitHub Actions runs two stages:

- `quality`: Ruff, hardening policy check, pytest with coverage
- `compose-smoke`: bootstrap env, validate compose, build the stack, run end-to-end smoke, collect logs on failure

See [docs/hardening.md](./docs/hardening.md) for the third-wave event workload hardening scope.

## Evidence

Latest evidence bundle is collected into:

- `artifacts/evidence/compose-ps.txt`
- `artifacts/evidence/compose-logs.txt`
- `artifacts/evidence/compose-config.txt`

## Definition Of Done Status

This repository currently meets its portfolio `Definition of Done`:

- secure intake is demonstrable
- retries and DLQ are demonstrable
- metrics, traces, logs, and alerts are wired into the event lifecycle
- CI validates happy path and failure path
- repo-local hardening check validates runtime and CI guardrails
- the repo reads like a real event ingestion platform, not a toy webhook endpoint

## Known Limitations

- this is a single-node local demo, not a clustered production deployment
- logs are structured and collectible, but `Loki` is not included yet
- there is no outbox pattern yet between DB commit and broker publish
- no `k6` load generator or chaos drill is implemented yet

## Future Improvements

- add `Loki` for log search and retention
- add explicit outbox/inbox pattern discussion and implementation
- add `k6` load drills
- add failure-injection tooling for broker and worker outages
- add partner-specific contract fixtures and replay tooling
