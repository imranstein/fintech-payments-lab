import hashlib
import json
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import provider
from app.db import get_db
from app.models import Order, Payment
from app.schemas import OrderCreate, OrderOut, PaymentCreate, PaymentOut

app = FastAPI(title="Fintech Payments Lab")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    order = Order(amount_minor=payload.amount_minor, currency=payload.currency)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def request_hash(payload: PaymentCreate) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def replay(payment: Payment, body_hash: str) -> Payment:
    if payment.request_hash != body_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Idempotency-Key reused with a different request body")
    return payment


@app.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreate,
    idempotency_key: str = Header(min_length=1, max_length=255),
    db: Session = Depends(get_db),
):
    body_hash = request_hash(payload)
    by_key = select(Payment).where(Payment.idempotency_key == idempotency_key)

    existing = db.scalar(by_key)
    if existing:
        return replay(existing, body_hash)

    # FOR NO KEY UPDATE serialises payments for one order without blocking the payments FK insert
    order = db.get(Order, payload.order_id, with_for_update={"key_share": True})
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.status == "PAID":
        raise HTTPException(status.HTTP_409_CONFLICT, "Order is already paid")

    # ponytail: two racing requests can both reach charge(); harmless for the deterministic mock,
    # a real provider needs the key forwarded as its own idempotency key.
    payment_status, provider_ref = provider.charge(order.amount_minor, idempotency_key)
    payment = Payment(
        order_id=order.id,
        amount_minor=order.amount_minor,
        currency=order.currency,
        status=payment_status,
        provider_ref=provider_ref,
        idempotency_key=idempotency_key,
        request_hash=body_hash,
    )
    db.add(payment)
    if payment_status == "SUCCEEDED":
        order.status = "PAID"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return replay(db.scalar(by_key), body_hash)
    db.refresh(payment)
    return payment


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: uuid.UUID, db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return payment
