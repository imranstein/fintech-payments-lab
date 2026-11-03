# fintech-payments-lab

A small payments API used as the baseline for a backend study program. It creates orders, charges them through a
deterministic mock provider, and makes payment creation safe to retry with an `Idempotency-Key` header.

Stack: Python 3.12, FastAPI, SQLAlchemy 2.0 (sync), psycopg 3, Alembic, PostgreSQL 16, Docker Compose.

## Run it

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```

The first command starts the `api` and `db` services. The second creates the tables. Run it again after pulling new
migrations.

| Service  | On your machine         | Inside the container |
|----------|-------------------------|----------------------|
| API      | http://localhost:8050   | port 8000            |
| Postgres | localhost:5437          | port 5432            |

The host ports differ from the container ports on purpose. Uvicorn listens on 8000 and Postgres on 5432 inside their
containers, which are the standard ports. On the host they are published on 8050 and 5437 so they do not collide with
other projects or a locally installed Postgres. In each `"host:container"` pair in `docker-compose.yml`, the second
number must match the port the process really listens on inside its container. Inside the Compose network the API
reaches the database at `db:5432`.

Connect with psql from the host:

```bash
psql postgresql://payments:payments@localhost:5437/payments
```

The `payments` / `payments` credentials in `docker-compose.yml` and `.env.example` are local development values only.
They are not secrets and must never be used anywhere real.

## Endpoints

Money is always an integer in minor units (cents for USD), never a float.

### GET /health

```bash
curl http://localhost:8050/health
# {"status":"ok"}
```

### POST /orders

`amount_minor` must be greater than 0. `currency` is a 3-letter code and is stored in upper case. Invalid input
returns 422.

```bash
curl -X POST http://localhost:8050/orders \
  -H 'Content-Type: application/json' \
  -d '{"amount_minor": 2500, "currency": "usd"}'
# 201 {"id": "...", "amount_minor": 2500, "currency": "USD", "status": "CREATED", "created_at": "..."}
```

### POST /payments

Requires an `Idempotency-Key` header. The amount and currency come from the stored order, never from the request
body. Unknown `order_id` returns 404. A missing header returns 422.

```bash
curl -X POST http://localhost:8050/payments \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 7b1c2a3e-order-42-attempt' \
  -d '{"order_id": "<order id>"}'
# 201 {"id": "...", "order_id": "...", "amount_minor": 2500, "currency": "USD",
#      "status": "SUCCEEDED", "provider_ref": "mock_7b1c2a3e-order-42-attempt", "created_at": "..."}
```

The mock provider in `app/provider.py` has no randomness: amounts above 500000 minor units return `FAILED`, everything
else returns `SUCCEEDED`. A succeeded payment moves the order to `PAID`. Paying an order that is already `PAID`
with a new key returns 409, so an order is never charged twice. A `FAILED` payment leaves the order unpaid, so it can
be retried with a new key.

### GET /payments/{id}

```bash
curl http://localhost:8050/payments/<payment id>
# 200 with the payment, or 404
```

## Idempotency rules

Clients send a unique `Idempotency-Key` with each payment attempt and reuse the same key when they retry it.

- Same key and same body: the API returns the original payment. The provider is not charged again and no second row is
  written.
- Same key but a different body: the API returns 409 Conflict. A key belongs to exactly one request.
- Two identical requests arriving at the same moment: the database has a UNIQUE constraint on
  `payments.idempotency_key`, so only one insert can win. The loser rolls back and returns the winning payment instead
  of an error.

"Same body" is checked with a SHA-256 hash of the request body in a canonical form (sorted keys, no whitespace),
stored with the payment as `request_hash`.

## Tests and linting

Tests run against a real PostgreSQL started by Testcontainers, so Docker must be running.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest -v
```

GitHub Actions runs the same ruff and pytest steps on every push (`.github/workflows/ci.yml`).
