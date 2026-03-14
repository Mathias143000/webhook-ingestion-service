# Webhook Ingestion Service

Асинхронный сервис приема webhook-событий на FastAPI и async SQLAlchemy.

Проект сфокусирован на типовом интеграционном сценарии: прием внешних событий, проверка подписи, идемпотентность, Redis-backed очередь, отдельный worker и operational endpoints.

## Что здесь важно

- опциональная HMAC-проверка входящих webhook-запросов
- идемпотентность по delivery ID
- статусы обработки `pending`, `processed`, `failed`
- Redis-backed queue для отделения приема webhook от обработки
- отдельный worker-процесс для асинхронной обработки событий
- operational endpoints для просмотра состояния очереди
- request ID в логах
- health checks, Docker-конфигурация и CI

## Стек

- Python 3.11
- FastAPI + Uvicorn
- SQLAlchemy 2.0 async
- PostgreSQL для runtime
- Redis для очереди и worker orchestration
- SQLite для локальной разработки и тестов
- Pydantic Settings
- pytest + pytest-asyncio + httpx
- Ruff
- Docker Compose
- GitHub Actions

## Структура проекта

```text
app/
  main.py               # bootstrap приложения, lifecycle, middleware, /health
  config.py             # конфигурация через env
  db.py                 # async engine, sessions, db ping/init/dispose
  models.py             # Event ORM model и поля жизненного цикла
  queue.py              # enqueue/dequeue, queue health, Redis integration
  schemas.py            # контракты запросов и ответов
  security.py           # HMAC verification для входящих webhook
  crud.py               # операции сохранения и reporting queries
  routers/webhooks.py   # API endpoints
  services/processor.py # обработка событий
  worker.py             # отдельный worker-процесс для очереди
tests/
  conftest.py
  test_health.py
  test_webhook.py
```

## Runtime Architecture

```text
Webhook sender
      |
      v
[FastAPI app]
  verify signature / idempotency
  persist event metadata
      |
      v
[Redis queue]
      |
      v
[Worker]
  process event
  update processing_status / attempts / error_message
      |
      v
[PostgreSQL]
```

## API

### `GET /health`

Возвращает статус сервиса, базы данных и очереди.

```json
{
  "status": "ok",
  "database": "ok",
  "queue": "ok",
  "queue_depth": 0,
  "queue_backend": "redis",
  "version": "1.2.0"
}
```

### `POST /webhook`

Принимает событие, сохраняет его и ставит в очередь на обработку.

Тело запроса:

```json
{
  "source": "telegram_bot",
  "event_type": "user_registered",
  "payload": {
    "user_id": 123,
    "username": "john_doe"
  }
}
```

Поддерживаемые заголовки:

- `X-API-KEY`, если включена API key protection
- `X-Webhook-ID` для идемпотентности
- `X-Webhook-Timestamp` и `X-Webhook-Signature`, если задан `WEBHOOK_SECRET`

Ответ при первом приеме:

```json
{
  "status": "accepted",
  "event_id": "9a40f4f6-5b7b-4c18-a6ad-4fd419e3c6f4",
  "delivery_id": "delivery-123"
}
```

Ответ на повторную доставку:

```json
{
  "status": "duplicate",
  "event_id": "9a40f4f6-5b7b-4c18-a6ad-4fd419e3c6f4",
  "delivery_id": "delivery-123"
}
```

### `GET /events`

Возвращает пагинированный список событий с метаданными обработки.

Параметры:

- `limit` от `1` до `100`
- `offset` больше или равен `0`
- `source` - опциональный фильтр по источнику

### `GET /events/summary`

Возвращает краткую operational-сводку:

```json
{
  "total": 12,
  "pending": 1,
  "processed": 10,
  "failed": 1,
  "queue_depth": 2,
  "by_source": {
    "stripe": 7,
    "telegram_bot": 5
  }
}
```

### `GET /queue/stats`

Возвращает состояние очереди:

```json
{
  "backend": "redis",
  "enabled": true,
  "queue_name": "webhook-events",
  "depth": 2
}
```

### `POST /events/{event_id}/retry`

Повторно ставит в обработку событие, если оно еще не дошло до `processed`, и возвращает `202 Accepted`.

Swagger/OpenAPI доступен по `GET /docs`.

## Security и надежность

- API key protection опциональна и использует constant-time comparison
- HMAC verification защищает от поддельных webhook-запросов
- Timestamp tolerance уменьшает риск replay-атак
- Идемпотентность по delivery ID предотвращает дубликаты
- Ошибки обработки сохраняются через `error_message` и `processing_attempts`
- Каждый ответ содержит `X-Request-ID` для трассировки в логах

Это тот слой, который и делает проект заметно сильнее “обычного webhook receiver”.

## Переменные окружения

См. `.env.example`.

- `DATABASE_URL` - строка подключения async SQLAlchemy
- `API_KEY` - опциональный API key для защищенных endpoints
- `APP_NAME` - имя сервиса в логах
- `LOG_LEVEL` - уровень логирования
- `AUTO_CREATE_TABLES` - автоматически создавать таблицы при старте
- `TASK_QUEUE_BACKEND` - `inline` для локального упрощенного режима или `redis` для worker queue
- `REDIS_URL` - адрес Redis для очереди
- `EVENT_QUEUE_NAME` - имя Redis list, через которую app общается с worker
- `WORKER_POLL_TIMEOUT_SECONDS` - timeout для очередного poll в worker
- `WEBHOOK_SECRET` - включает HMAC validation
- `WEBHOOK_SIGNATURE_HEADER` - имя заголовка с подписью
- `WEBHOOK_TIMESTAMP_HEADER` - имя заголовка с timestamp
- `WEBHOOK_ID_HEADER` - имя заголовка с delivery ID
- `WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS` - допустимое окно для replay protection

## Быстрый старт

### Локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
# Optional infra mode:
# export TASK_QUEUE_BACKEND=inline
uvicorn app.main:app --reload
```

Для Windows:

```powershell
.venv\Scripts\activate
```

Сервис будет доступен на `http://localhost:8000`, документация - на `http://localhost:8000/docs`.
По умолчанию локальный запуск использует `inline`-режим без Redis. Полный infra-стенд поднимается через Docker Compose.

### Docker

```bash
cp .env.example .env
docker compose up --build
```

После старта доступны:

- API: `http://localhost:8000`
- PostgreSQL
- Redis
- отдельный `worker` контейнер

## Проверка качества

```bash
python -m ruff check app tests
python -m pytest -q
```

CI автоматически запускает lint и тесты с coverage report в GitHub Actions.

## Заметки

- Docker-стенд использует Redis queue и отдельный worker, чтобы отделить прием webhook от обработки и показать более реалистичную интеграционную схему.
- Для упрощенного локального режима остается `inline` backend без Redis, чтобы проект можно было запускать даже без инфраструктурных зависимостей.
- `delivery_id` используется как ключ идемпотентности, чтобы повторная доставка не портила состояние.
- Operational summary строится агрегирующими запросами к БД, а не полным чтением всех событий в память.
- SQLite остается вариантом для локальной разработки и тестов, а runtime-стенд ориентирован на PostgreSQL + Redis.
