import uuid

from sqlalchemy import func, select


def pay(client, order_id, key):
    return client.post("/payments", json={"order_id": str(order_id)}, headers={"Idempotency-Key": key})


def payment_rows(db, key):
    from app.models import Payment

    return db.scalar(select(func.count()).select_from(Payment).where(Payment.idempotency_key == key))


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_order(client):
    r = client.post("/orders", json={"amount_minor": 1999, "currency": "eur"})
    assert r.status_code == 201
    body = r.json()
    assert body["amount_minor"] == 1999
    assert body["currency"] == "EUR"
    assert body["status"] == "CREATED"
    uuid.UUID(body["id"])
    assert body["created_at"].endswith("Z") or "+" in body["created_at"]


def test_create_order_negative_amount(client):
    r = client.post("/orders", json={"amount_minor": -5, "currency": "USD"})
    assert r.status_code == 422


def test_create_payment_marks_order_paid(client, db, order):
    from app.models import Order

    key = str(uuid.uuid4())
    r = pay(client, order["id"], key)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "SUCCEEDED"
    assert body["amount_minor"] == 2500
    assert body["currency"] == "USD"
    assert body["provider_ref"] == f"mock_{key}"
    assert db.get(Order, uuid.UUID(order["id"])).status == "PAID"


def test_amount_over_limit_fails(client):
    big = client.post("/orders", json={"amount_minor": 500_001, "currency": "USD"}).json()
    r = pay(client, big["id"], str(uuid.uuid4()))
    assert r.status_code == 201
    assert r.json()["status"] == "FAILED"


def test_replay_same_key_same_body(client, db, order):
    key = str(uuid.uuid4())
    first = pay(client, order["id"], key)
    second = pay(client, order["id"], key)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert payment_rows(db, key) == 1


def test_same_key_different_body_conflicts(client, order):
    other = client.post("/orders", json={"amount_minor": 100, "currency": "USD"}).json()
    key = str(uuid.uuid4())
    assert pay(client, order["id"], key).status_code == 201
    assert pay(client, other["id"], key).status_code == 409


def test_paid_order_rejects_new_key(client, db, order):
    from app.models import Payment

    assert pay(client, order["id"], str(uuid.uuid4())).status_code == 201
    assert pay(client, order["id"], str(uuid.uuid4())).status_code == 409
    rows = db.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == uuid.UUID(order["id"])))
    assert rows == 1


def test_concurrent_new_keys_charge_once(client, order, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app import provider

    real_charge = provider.charge

    def slow_charge(amount_minor, idempotency_key):
        time.sleep(0.2)
        return real_charge(amount_minor, idempotency_key)

    monkeypatch.setattr(provider, "charge", slow_charge)
    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = sorted(pool.map(lambda _: pay(client, order["id"], str(uuid.uuid4())).status_code, range(5)))
    assert codes == [201, 409, 409, 409, 409]


def test_missing_idempotency_key(client, order):
    r = client.post("/payments", json={"order_id": order["id"]})
    assert r.status_code == 422


def test_unknown_order(client):
    assert pay(client, uuid.uuid4(), str(uuid.uuid4())).status_code == 404


def test_concurrent_duplicate_replays_winner(client, db, order, monkeypatch):
    from app import provider
    from app.db import SessionLocal
    from app.main import request_hash
    from app.models import Payment
    from app.schemas import PaymentCreate

    key = str(uuid.uuid4())
    winner_id = uuid.uuid4()
    real_charge = provider.charge

    def charge_while_another_request_commits(amount_minor, idempotency_key):
        with SessionLocal() as other:
            other.add(Payment(
                id=winner_id,
                order_id=uuid.UUID(order["id"]),
                amount_minor=amount_minor,
                currency="USD",
                status="SUCCEEDED",
                provider_ref=f"mock_{idempotency_key}",
                idempotency_key=idempotency_key,
                request_hash=request_hash(PaymentCreate(order_id=order["id"])),
            ))
            other.commit()
        return real_charge(amount_minor, idempotency_key)

    monkeypatch.setattr(provider, "charge", charge_while_another_request_commits)
    r = pay(client, order["id"], key)
    assert r.status_code == 201
    assert r.json()["id"] == str(winner_id)
    assert payment_rows(db, key) == 1


def test_get_payment(client, order):
    created = pay(client, order["id"], str(uuid.uuid4())).json()
    r = client.get(f"/payments/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_get_unknown_payment(client):
    assert client.get(f"/payments/{uuid.uuid4()}").status_code == 404
