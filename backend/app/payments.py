"""Fictional payment reference data shared across workflows.

Refund exceptions and chargebacks both carry a `payment_reference`; this table links a
reference to its captured amount and, where known, the customer's KYC case. Read-only in
the app; rows come from `app.seed`.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime


class Payment(Base):
    __tablename__ = "payments"

    reference: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_kyc_id: Mapped[str | None] = mapped_column(ForeignKey("kyc_cases.id"))
    amount_minor: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))
    captured_at: Mapped[datetime]
    card_last4: Mapped[str] = mapped_column(String(4))
    description: Mapped[str] = mapped_column(String(200))


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reference: str
    customer_kyc_id: str | None
    amount_minor: int
    currency: str
    captured_at: UTCDateTime
    card_last4: str
    description: str
