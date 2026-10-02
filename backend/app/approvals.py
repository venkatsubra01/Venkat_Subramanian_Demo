"""Shared approval requests. The supervisor inbox route lives in `work.py`.

The inbox only lists and coordinates. Each source app owns its own approval rules and
endpoints (today only chargeback evidence approval, in `chargebacks.py`); the helpers here hold
the rules that apply to every approval: a pending request, decided once, never by its requester.
"""

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .activity import record_activity
from .auth import SYSTEM, Identity
from .db import Base, UTCDateTime, utcnow

ApprovalState = Literal["pending", "approved", "returned", "invalidated"]
SnapshotValue = str | int | bool | None | list[dict[str, str | int | bool | None]]


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_app: Mapped[str] = mapped_column(String(16), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    evidence_version: Mapped[int]
    # What the approver is shown and what the decision refers to (no file contents).
    snapshot: Mapped[dict[str, SnapshotValue]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), index=True)
    requested_by_id: Mapped[str] = mapped_column(String(32))
    requested_by_name: Mapped[str] = mapped_column(String(100))
    requested_at: Mapped[UTCDateTime] = mapped_column(default=utcnow)
    decided_by_id: Mapped[str | None] = mapped_column(String(32))
    decided_by_name: Mapped[str | None] = mapped_column(String(100))
    decided_at: Mapped[UTCDateTime | None]
    decision_reason: Mapped[str | None] = mapped_column(Text)
    invalidated_at: Mapped[UTCDateTime | None]
    invalidated_reason: Mapped[str | None] = mapped_column(Text)


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_app: str
    source_id: str
    kind: str
    evidence_version: int
    snapshot: dict[str, SnapshotValue]
    state: str
    requested_by_id: str
    requested_by_name: str
    requested_at: UTCDateTime
    decided_by_id: str | None
    decided_by_name: str | None
    decided_at: UTCDateTime | None
    decision_reason: str | None
    invalidated_at: UTCDateTime | None
    invalidated_reason: str | None


def requests_for(db: Session, source_app: str, source_id: str) -> list[ApprovalRequest]:
    query = (
        select(ApprovalRequest)
        .where(ApprovalRequest.source_app == source_app, ApprovalRequest.source_id == source_id)
        .order_by(ApprovalRequest.id.desc())
    )
    return list(db.scalars(query))


def get_request(db: Session, source_app: str, source_id: str, approval_id: int) -> ApprovalRequest:
    request = db.get(ApprovalRequest, approval_id)
    if request is None or request.source_app != source_app or request.source_id != source_id:
        raise HTTPException(status_code=404, detail=f"Approval request {approval_id} not found on {source_id}.")
    return request


def create_request(
    db: Session,
    *,
    requester: Identity,
    source_app: str,
    source_id: str,
    kind: str,
    evidence_version: int,
    snapshot: dict[str, SnapshotValue],
) -> ApprovalRequest:
    pending = [r for r in requests_for(db, source_app, source_id) if r.state == "pending"]
    if pending:
        raise HTTPException(status_code=409, detail=f"Approval request {pending[0].id} is already pending.")
    request = ApprovalRequest(
        source_app=source_app,
        source_id=source_id,
        kind=kind,
        evidence_version=evidence_version,
        snapshot=snapshot,
        state="pending",
        requested_by_id=requester.id,
        requested_by_name=requester.name,
        requested_at=utcnow(),
    )
    db.add(request)
    db.flush()
    record_activity(
        db,
        actor=requester,
        record_type=source_app,
        record_id=source_id,
        action="approval_requested",
        approval_id=request.id,
        after={"state": "pending", "evidence_version": evidence_version},
        note=f"Evidence version {evidence_version} submitted for approval.",
    )
    return request


def check_decision_allowed(request: ApprovalRequest, approver: Identity, reviewed_version: int, current_version: int) -> None:
    """Rules shared by every approval decision. Raises 403/409; changes nothing."""
    if approver.id == request.requested_by_id:
        raise HTTPException(status_code=403, detail="You cannot decide on an approval you requested.")
    if request.state != "pending":
        raise HTTPException(status_code=409, detail=f"Approval request {request.id} is {request.state}, not pending.")
    if reviewed_version != request.evidence_version or request.evidence_version != current_version:
        raise HTTPException(
            status_code=409,
            detail=f"Stale evidence version: request is for v{request.evidence_version}, you reviewed "
            f"v{reviewed_version}, current is v{current_version}.",
        )


def decide_request(
    db: Session, request: ApprovalRequest, *, approver: Identity, approve: bool, reason: str | None
) -> None:
    previous = request.state
    request.state = "approved" if approve else "returned"
    request.decided_by_id = approver.id
    request.decided_by_name = approver.name
    request.decided_at = utcnow()
    request.decision_reason = reason
    record_activity(
        db,
        actor=approver,
        record_type=request.source_app,
        record_id=request.source_id,
        action="approval_approved" if approve else "approval_returned",
        approval_id=request.id,
        before={"state": previous},
        after={"state": request.state, "evidence_version": request.evidence_version},
        note=reason,
    )


def invalidate_open_requests(db: Session, source_app: str, source_id: str, reason: str) -> list[ApprovalRequest]:
    """Pending or granted approvals stop counting once what they covered changes."""
    invalidated = []
    for request in requests_for(db, source_app, source_id):
        if request.state not in ("pending", "approved"):
            continue
        previous = request.state
        request.state = "invalidated"
        request.invalidated_at = utcnow()
        request.invalidated_reason = reason
        record_activity(
            db,
            actor=SYSTEM,
            record_type=source_app,
            record_id=source_id,
            action="approval_invalidated",
            approval_id=request.id,
            before={"state": previous},
            after={"state": "invalidated", "evidence_version": request.evidence_version},
            note=reason,
        )
        invalidated.append(request)
    return invalidated
