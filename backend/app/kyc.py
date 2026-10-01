"""KYC review workflow: model, schemas, transition rules and routes.

The statuses and rules are demo assumptions, not a compliance policy.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .activity import record_activity
from .auth import CurrentUser, Reviewer
from .db import Base, UTCDateTime, get_db

RECORD_TYPE = "kyc"

KycStatus = Literal["pending_review", "awaiting_information", "approved", "rejected"]
KycAction = Literal["approve", "reject", "request_information", "return_to_review"]
RiskLabel = Literal["low", "medium", "high"]

TRANSITIONS: dict[str, dict[str, str]] = {
    "pending_review": {
        "approve": "approved",
        "reject": "rejected",
        "request_information": "awaiting_information",
    },
    "awaiting_information": {
        "return_to_review": "pending_review",
    },
    "approved": {},
    "rejected": {},
}
NOTE_REQUIRED: frozenset[str] = frozenset({"reject", "request_information", "return_to_review"})


class KycCase(Base):
    __tablename__ = "kyc_cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(100), index=True)
    submitted_at: Mapped[datetime]
    risk_label: Mapped[str] = mapped_column(String(16))
    check_summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)


class KycCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_name: str
    submitted_at: UTCDateTime
    risk_label: str
    check_summary: str
    status: str


class KycCaseDetail(KycCaseOut):
    allowed_actions: list[str]


class KycListOut(BaseModel):
    items: list[KycCaseOut]
    status_counts: dict[str, int]


class KycDecisionIn(BaseModel):
    action: KycAction
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def note_required_for_action(self) -> "KycDecisionIn":
        self.note = self.note.strip() if self.note else None
        if self.action in NOTE_REQUIRED and not self.note:
            raise ValueError(f"A note is required for '{self.action}'.")
        return self


def _detail(case: KycCase) -> KycCaseDetail:
    return KycCaseDetail(
        **KycCaseOut.model_validate(case).model_dump(),
        allowed_actions=list(TRANSITIONS[case.status]),
    )


def _get_case(db: Session, case_id: str) -> KycCase:
    case = db.get(KycCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"KYC case {case_id} not found.")
    return case


router = APIRouter(prefix="/api/kyc", tags=["kyc"])


@router.get("", response_model=KycListOut)
def list_cases(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    status: KycStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> KycListOut:
    query = select(KycCase)
    if search and search.strip():
        query = query.where(KycCase.customer_name.ilike(f"%{search.strip()}%"))
    if status is not None:
        query = query.where(KycCase.status == status)
    query = query.order_by(KycCase.submitted_at.asc()).limit(limit)
    counts = dict(db.execute(select(KycCase.status, func.count()).group_by(KycCase.status)).all())
    return KycListOut(
        items=[KycCaseOut.model_validate(c) for c in db.scalars(query)],
        status_counts={s: counts.get(s, 0) for s in TRANSITIONS},
    )


@router.get("/{case_id}", response_model=KycCaseDetail)
def get_case(case_id: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> KycCaseDetail:
    return _detail(_get_case(db, case_id))


@router.post("/{case_id}/decision", response_model=KycCaseDetail)
def decide(
    case_id: str,
    body: KycDecisionIn,
    reviewer: Reviewer,
    db: Annotated[Session, Depends(get_db)],
) -> KycCaseDetail:
    case = _get_case(db, case_id)
    previous = case.status
    new_status = TRANSITIONS[previous].get(body.action)
    if new_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot '{body.action}' a case in status '{previous}'.",
        )
    case.status = new_status
    record_activity(
        db,
        actor=reviewer,
        record_type=RECORD_TYPE,
        record_id=case.id,
        action=body.action,
        previous_status=previous,
        new_status=new_status,
        note=body.note,
    )
    db.commit()
    return _detail(case)
