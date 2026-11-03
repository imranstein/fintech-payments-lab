import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderCreate(BaseModel):
    amount_minor: int = Field(gt=0, le=2**63 - 1)
    currency: str

    @field_validator("currency")
    @classmethod
    def currency_must_be_three_letters(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError("currency must be a 3-letter code")
        return v


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount_minor: int
    currency: str
    status: str
    created_at: datetime


class PaymentCreate(BaseModel):
    order_id: uuid.UUID


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    amount_minor: int
    currency: str
    status: str
    provider_ref: str
    created_at: datetime
