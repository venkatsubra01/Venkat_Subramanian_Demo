"""Refund exception workflow: model, schemas, transition rules, routes and the
inbound demo event endpoint.

"Resolve" records an operational decision. Nothing here retries or issues a payment.
"""

from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .activity import record_activity
from .auth import CurrentUser, Reviewer
from .db import Base, UTCDateTime, get_db, utcnow
from .tasks import WorkTask, sync_task

RECORD_TYPE = "refund"

RefundStatus = Literal["open", "escalated", "resolved"]
RefundAction = Literal["escalate", "resolve"]

TRANSITIONS: dict[str, dict[str, str]] = {
    "open": {"escalate": "escalated", "resolve": "resolved"},
    "escalated": {"resolve": "resolved"},
    "resolved": {},
}
ACTIONABLE: frozenset[str] = frozenset({"open", "escalated"})


class RefundException(Base):
    __tablename__ = "refund_exceptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    external_event_id: Mapped[str] = mapped_column(String(64), unique=True)
    payment_reference: Mapped[str] = mapped_column(String(64))
    amount_minor: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))
    failure_reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[UTCDateTime] = mapped_column(default=utcnow)


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_event_id: str
    payment_reference: str
    amount_minor: int
    currency: str
    failure_reason: str
    status: str
    created_at: UTCDateTime


class RefundDetail(RefundOut):
    allowed_actions: list[str]


class RefundListOut(BaseModel):
    items: list[RefundOut]
    status_counts: dict[str, int]


class RefundDecisionIn(BaseModel):
    action: RefundAction
    note: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def note_not_blank(self) -> "RefundDecisionIn":
        self.note = self.note.strip()
        if not self.note:
            raise ValueError(f"A note is required for '{self.action}'.")
        return self


class RefundFailedEventIn(BaseModel):
    event_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    payment_reference: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    amount_minor: int = Field(gt=0, le=1_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    failure_reason: str = Field(min_length=1, max_length=500)


class RefundEventResult(BaseModel):
    created: bool
    exception: RefundDetail


def _detail(record: RefundException) -> RefundDetail:
    return RefundDetail(
        **RefundOut.model_validate(record).model_dump(),
        allowed_actions=list(TRANSITIONS[record.status]),
    )


def sync_record_task(db: Session, record: RefundException) -> WorkTask | None:
    return sync_task(
        db,
        source_app=RECORD_TYPE,
        source_id=record.id,
        source_status=record.status,
        actionable=record.status in ACTIONABLE,
        priority="high" if record.status == "escalated" else "normal",
    )


def _get_record(db: Session, refund_id: str) -> RefundException:
    record = db.get(RefundException, refund_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Refund exception {refund_id} not found.")
    return record


def _same_business_fields(record: RefundException, event: RefundFailedEventIn) -> bool:
    return (
        record.payment_reference == event.payment_reference
        and record.amount_minor == event.amount_minor
        and record.currency == event.currency
        and record.failure_reason == event.failure_reason
    )


def _find_by_event(db: Session, event_id: str) -> RefundException | None:
    return db.scalar(select(RefundException).where(RefundException.external_event_id == event_id))


def _replay_result(record: RefundException, event: RefundFailedEventIn) -> RefundEventResult:
    if not _same_business_fields(record, event):
        raise HTTPException(
            status_code=409,
            detail=f"Event id {event.event_id} was already used with different details.",
        )
    return RefundEventResult(created=False, exception=_detail(record))


router = APIRouter(prefix="/api/refunds", tags=["refunds"])


@router.get("", response_model=RefundListOut)
def list_refunds(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    status: RefundStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RefundListOut:
    query = select(RefundException)
    if status is not None:
        query = query.where(RefundException.status == status)
    query = query.order_by(RefundException.created_at.desc()).limit(limit)
    counts: dict[str, int] = {s: 0 for s in TRANSITIONS}
    for record_status in db.scalars(select(RefundException.status)):
        counts[record_status] = counts.get(record_status, 0) + 1
    return RefundListOut(
        items=[RefundOut.model_validate(r) for r in db.scalars(query)],
        status_counts=counts,
    )


@router.get("/{refund_id}", response_model=RefundDetail)
def get_refund(refund_id: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> RefundDetail:
    return _detail(_get_record(db, refund_id))


@router.post("/{refund_id}/decision", response_model=RefundDetail)
def decide(
    refund_id: str,
    body: RefundDecisionIn,
    reviewer: Reviewer,
    db: Annotated[Session, Depends(get_db)],
) -> RefundDetail:
    record = _get_record(db, refund_id)
    previous = record.status
    new_status = TRANSITIONS[previous].get(body.action)
    if new_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot '{body.action}' a refund exception in status '{previous}'.",
        )
    record.status = new_status
    record_activity(
        db,
        actor=reviewer,
        record_type=RECORD_TYPE,
        record_id=record.id,
        action=body.action,
        previous_status=previous,
        new_status=new_status,
        note=body.note,
    )
    if new_status == "resolved":
        record_activity(
            db,
            actor=reviewer,
            record_type=RECORD_TYPE,
            record_id=record.id,
            action="notification_simulated",
            previous_status=None,
            new_status=None,
            note=f"Local simulated notification (not delivered): {record.id} resolved.",
        )
    sync_record_task(db, record)
    db.commit()
    return _detail(record)


events_router = APIRouter(prefix="/api/demo/events", tags=["demo"])


@events_router.post("/refund-failed", response_model=RefundEventResult, status_code=201)
def refund_failed_event(
    event: RefundFailedEventIn,
    reviewer: Reviewer,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RefundEventResult:
    """Inbound-event demonstration endpoint. Not a payment-provider webhook."""
    existing = _find_by_event(db, event.event_id)
    if existing is not None:
        response.status_code = 200
        return _replay_result(existing, event)

    record = RefundException(
        id=f"RFX-{uuid4().hex[:8].upper()}",
        external_event_id=event.event_id,
        payment_reference=event.payment_reference,
        amount_minor=event.amount_minor,
        currency=event.currency,
        failure_reason=event.failure_reason,
        status="open",
        created_at=utcnow(),
    )
    db.add(record)
    record_activity(
        db,
        actor=reviewer,
        record_type=RECORD_TYPE,
        record_id=record.id,
        action="created_from_event",
        previous_status=None,
        new_status="open",
        note=f"refund.failed event {event.event_id}: {event.failure_reason}",
    )
    try:
        db.flush()
        sync_record_task(db, record)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_by_event(db, event.event_id)
        if existing is None:
            raise
        response.status_code = 200
        return _replay_result(existing, event)
    return RefundEventResult(created=True, exception=_detail(record))
