"""Chargeback evidence workspace: disputes, evidence checklist, case notes, attachments,
workflow transitions and a downloadable PDF evidence summary.

Deadlines, reasons and checklist items are demo assumptions. Nothing here contacts a
payment provider or submits a dispute.
"""

import hashlib
import re
import shutil
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .activity import Activity, record_activity
from .auth import CurrentUser, Identity, Reviewer
from .config import ATTACHMENTS_DIR
from .db import Base, UTCDateTime, get_db, utcnow
from .kyc import KycCase
from .payments import Payment, PaymentOut
from .pdf import TextPdf
from .refunds import RefundException, RefundOut

RECORD_TYPE = "chargeback"

ChargebackStatus = Literal["open", "collecting_evidence", "ready_for_review", "closed"]
ChargebackAction = Literal["start_collecting", "mark_ready", "close"]
ChargebackReason = Literal["fraudulent", "product_not_received", "duplicate_charge", "credit_not_processed"]
ChargebackOutcome = Literal["won", "lost", "accepted", "withdrawn"]

TRANSITIONS: dict[str, dict[str, str]] = {
    "open": {"start_collecting": "collecting_evidence"},
    "collecting_evidence": {"mark_ready": "ready_for_review"},
    "ready_for_review": {"close": "closed"},
    "closed": {},
}

COMMON_CHECKLIST = [("receipt", "Receipt or invoice for the payment")]
CHECKLIST_BY_REASON: dict[str, list[tuple[str, str]]] = {
    "fraudulent": [
        ("identity_verification", "Customer identity verification (linked KYC case)"),
        ("avs_cvv", "AVS / CVV match result"),
        ("device_ip", "Device and IP details for the purchase"),
        ("prior_history", "Prior undisputed payments by the same customer"),
    ],
    "product_not_received": [
        ("proof_of_delivery", "Proof of delivery or service"),
        ("tracking", "Carrier tracking record"),
        ("customer_comms", "Customer communication about delivery"),
    ],
    "duplicate_charge": [
        ("distinct_charges", "Evidence the charges are for distinct purchases"),
        ("refund_records", "Refund records for this payment"),
    ],
    "credit_not_processed": [
        ("refund_policy", "Refund policy shown to the customer"),
        ("refund_records", "Refund records for this payment"),
        ("customer_comms", "Customer communication about the refund"),
    ],
}

ALLOWED_ATTACHMENT_TYPES: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "text/plain": (".txt",),
}
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_CASE = 20

SUMMARY_DISCLAIMER = (
    "Internal working summary generated from local demo data. It is NOT a complete dispute submission "
    "package: it lists evidence files but does not include their contents, has not been reviewed for "
    "card-network requirements, and has not been sent to any payment provider."
)


class Chargeback(Base):
    __tablename__ = "chargebacks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    payment_reference: Mapped[str] = mapped_column(String(64), index=True)
    cardholder_name: Mapped[str] = mapped_column(String(100))
    amount_minor: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(String(32))
    evidence_due_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    notes_updated_by: Mapped[str | None] = mapped_column(String(100))
    notes_updated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    closed_at: Mapped[datetime | None]


class ChecklistItem(Base):
    __tablename__ = "chargeback_checklist_items"
    __table_args__ = (UniqueConstraint("chargeback_id", "item_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chargeback_id: Mapped[str] = mapped_column(ForeignKey("chargebacks.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(200))
    position: Mapped[int]
    done: Mapped[bool] = mapped_column(default=False)
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime | None]


class Attachment(Base):
    __tablename__ = "chargeback_attachments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    chargeback_id: Mapped[str] = mapped_column(ForeignKey("chargebacks.id"), index=True)
    filename: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(String(100))
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)


def checklist_for_reason(reason: str) -> list[tuple[str, str]]:
    return COMMON_CHECKLIST + CHECKLIST_BY_REASON[reason]


def attachment_path(chargeback_id: str, attachment_id: str):
    return ATTACHMENTS_DIR / chargeback_id / attachment_id


def clear_attachment_files() -> None:
    shutil.rmtree(ATTACHMENTS_DIR, ignore_errors=True)


# ---------------------------------------------------------------- schemas


class ChargebackOut(BaseModel):
    id: str
    payment_reference: str
    cardholder_name: str
    amount_minor: int
    currency: str
    reason: str
    evidence_due_at: UTCDateTime
    status: str
    outcome: str | None
    created_at: UTCDateTime
    closed_at: UTCDateTime | None
    is_overdue: bool


class CustomerSummary(BaseModel):
    kyc_case_id: str
    customer_name: str
    risk_label: str
    kyc_status: str
    check_summary: str


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_key: str
    label: str
    done: bool
    updated_by: str | None
    updated_at: UTCDateTime | None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by: str
    uploaded_at: UTCDateTime


class ChargebackDetail(ChargebackOut):
    allowed_actions: list[str]
    notes: str
    notes_updated_by: str | None
    notes_updated_at: UTCDateTime | None
    payment: PaymentOut | None
    customer: CustomerSummary | None
    refunds: list[RefundOut]
    checklist: list[ChecklistItemOut]
    attachments: list[AttachmentOut]
    missing_information: list[str]


class ChargebackListOut(BaseModel):
    items: list[ChargebackOut]
    status_counts: dict[str, int]
    overdue_count: int


class ChargebackDecisionIn(BaseModel):
    action: ChargebackAction
    outcome: ChargebackOutcome | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def outcome_only_when_closing(self) -> "ChargebackDecisionIn":
        self.note = self.note.strip() if self.note else None
        if self.action == "close" and self.outcome is None:
            raise ValueError("A closing outcome is required to close a case.")
        if self.action != "close" and self.outcome is not None:
            raise ValueError("An outcome can only be set when closing a case.")
        return self


class ChecklistUpdateIn(BaseModel):
    done: bool


class NotesUpdateIn(BaseModel):
    notes: str = Field(max_length=5000)


# ---------------------------------------------------------------- helpers


def _is_overdue(chargeback: Chargeback) -> bool:
    return chargeback.status != "closed" and chargeback.evidence_due_at < utcnow()


def _summary(chargeback: Chargeback) -> ChargebackOut:
    return ChargebackOut(
        id=chargeback.id,
        payment_reference=chargeback.payment_reference,
        cardholder_name=chargeback.cardholder_name,
        amount_minor=chargeback.amount_minor,
        currency=chargeback.currency,
        reason=chargeback.reason,
        evidence_due_at=chargeback.evidence_due_at,
        status=chargeback.status,
        outcome=chargeback.outcome,
        created_at=chargeback.created_at,
        closed_at=chargeback.closed_at,
        is_overdue=_is_overdue(chargeback),
    )


def _get_chargeback(db: Session, chargeback_id: str) -> Chargeback:
    chargeback = db.get(Chargeback, chargeback_id)
    if chargeback is None:
        raise HTTPException(status_code=404, detail=f"Chargeback {chargeback_id} not found.")
    return chargeback


def _require_editable(chargeback: Chargeback) -> None:
    if chargeback.status == "closed":
        raise HTTPException(status_code=409, detail=f"Chargeback {chargeback.id} is closed; evidence is read-only.")


def _checklist(db: Session, chargeback_id: str) -> list[ChecklistItem]:
    query = select(ChecklistItem).where(ChecklistItem.chargeback_id == chargeback_id).order_by(ChecklistItem.position)
    return list(db.scalars(query))


def _attachments(db: Session, chargeback_id: str) -> list[Attachment]:
    query = select(Attachment).where(Attachment.chargeback_id == chargeback_id).order_by(Attachment.uploaded_at)
    return list(db.scalars(query))


def _linked_records(
    db: Session, chargeback: Chargeback
) -> tuple[Payment | None, KycCase | None, list[RefundException], list[str]]:
    missing: list[str] = []
    payment = db.get(Payment, chargeback.payment_reference)
    customer = None
    if payment is None:
        missing.append(f"No payment record found for reference {chargeback.payment_reference}.")
    elif payment.customer_kyc_id is None:
        missing.append("Payment is not linked to a KYC customer.")
    else:
        customer = db.get(KycCase, payment.customer_kyc_id)
        if customer is None:
            missing.append(f"Linked KYC case {payment.customer_kyc_id} was not found.")
    refunds = list(
        db.scalars(
            select(RefundException)
            .where(RefundException.payment_reference == chargeback.payment_reference)
            .order_by(RefundException.created_at)
        )
    )
    return payment, customer, refunds, missing


def _detail(db: Session, chargeback: Chargeback) -> ChargebackDetail:
    payment, customer, refunds, missing = _linked_records(db, chargeback)
    checklist = _checklist(db, chargeback.id)
    attachments = _attachments(db, chargeback.id)
    outstanding = sum(1 for item in checklist if not item.done)
    if outstanding:
        missing.append(f"{outstanding} of {len(checklist)} checklist items outstanding.")
    if not attachments:
        missing.append("No evidence files uploaded.")
    if not chargeback.notes.strip():
        missing.append("No case notes yet.")
    return ChargebackDetail(
        **_summary(chargeback).model_dump(),
        allowed_actions=list(TRANSITIONS[chargeback.status]),
        notes=chargeback.notes,
        notes_updated_by=chargeback.notes_updated_by,
        notes_updated_at=chargeback.notes_updated_at,
        payment=PaymentOut.model_validate(payment) if payment else None,
        customer=CustomerSummary(
            kyc_case_id=customer.id,
            customer_name=customer.customer_name,
            risk_label=customer.risk_label,
            kyc_status=customer.status,
            check_summary=customer.check_summary,
        )
        if customer
        else None,
        refunds=[RefundOut.model_validate(r) for r in refunds],
        checklist=[ChecklistItemOut.model_validate(i) for i in checklist],
        attachments=[AttachmentOut.model_validate(a) for a in attachments],
        missing_information=missing,
    )


def _safe_filename(filename: str) -> str:
    base = re.split(r"[\\/]", filename)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    return cleaned[:120]


def _content_matches(content_type: str, data: bytes) -> bool:
    if content_type == "application/pdf":
        return data.startswith(b"%PDF-")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _format_minor(amount_minor: int, currency: str) -> str:
    return f"{amount_minor / 100:,.2f} {currency} ({amount_minor} minor units)"


def _format_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "-"


# ---------------------------------------------------------------- routes

router = APIRouter(prefix="/api/chargebacks", tags=["chargebacks"])


@router.get("", response_model=ChargebackListOut)
def list_chargebacks(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    status: ChargebackStatus | None = None,
    overdue: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ChargebackListOut:
    now = utcnow()
    query = select(Chargeback)
    if status is not None:
        query = query.where(Chargeback.status == status)
    if overdue is True:
        query = query.where(Chargeback.status != "closed", Chargeback.evidence_due_at < now)
    elif overdue is False:
        query = query.where((Chargeback.status == "closed") | (Chargeback.evidence_due_at >= now))
    query = query.order_by(Chargeback.evidence_due_at.asc()).limit(limit)
    counts = dict(db.execute(select(Chargeback.status, func.count()).group_by(Chargeback.status)).all())
    overdue_count = db.scalar(
        select(func.count()).select_from(Chargeback).where(Chargeback.status != "closed", Chargeback.evidence_due_at < now)
    )
    return ChargebackListOut(
        items=[_summary(c) for c in db.scalars(query)],
        status_counts={s: counts.get(s, 0) for s in TRANSITIONS},
        overdue_count=overdue_count or 0,
    )


@router.get("/{chargeback_id}", response_model=ChargebackDetail)
def get_chargeback(chargeback_id: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> ChargebackDetail:
    return _detail(db, _get_chargeback(db, chargeback_id))


@router.post("/{chargeback_id}/decision", response_model=ChargebackDetail)
def decide(
    chargeback_id: str,
    body: ChargebackDecisionIn,
    reviewer: Reviewer,
    db: Annotated[Session, Depends(get_db)],
) -> ChargebackDetail:
    chargeback = _get_chargeback(db, chargeback_id)
    previous = chargeback.status
    new_status = TRANSITIONS[previous].get(body.action)
    if new_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot '{body.action}' a chargeback in status '{previous}'.",
        )
    chargeback.status = new_status
    note = body.note
    if body.action == "close":
        chargeback.outcome = body.outcome
        chargeback.closed_at = utcnow()
        note = f"Outcome: {body.outcome}." + (f" {body.note}" if body.note else "")
    record_activity(
        db,
        actor=reviewer,
        record_type=RECORD_TYPE,
        record_id=chargeback.id,
        action=body.action,
        previous_status=previous,
        new_status=new_status,
        note=note,
    )
    db.commit()
    return _detail(db, chargeback)


@router.put("/{chargeback_id}/checklist/{item_key}", response_model=ChargebackDetail)
def update_checklist_item(
    chargeback_id: str,
    item_key: str,
    body: ChecklistUpdateIn,
    reviewer: Reviewer,
    db: Annotated[Session, Depends(get_db)],
) -> ChargebackDetail:
    chargeback = _get_chargeback(db, chargeback_id)
    _require_editable(chargeback)
    item = db.scalar(
        select(ChecklistItem).where(ChecklistItem.chargeback_id == chargeback.id, ChecklistItem.item_key == item_key)
    )
    if item is None:
        raise HTTPException(status_code=404, detail=f"Checklist item {item_key} not found on {chargeback.id}.")
    if item.done != body.done:
        item.done = body.done
        item.updated_by = reviewer.name
        item.updated_at = utcnow()
        record_activity(
            db,
            actor=reviewer,
            record_type=RECORD_TYPE,
            record_id=chargeback.id,
            action="checklist_completed" if body.done else "checklist_reopened",
            previous_status=None,
            new_status=None,
            note=item.label,
        )
        db.commit()
    return _detail(db, chargeback)


@router.put("/{chargeback_id}/notes", response_model=ChargebackDetail)
def update_notes(
    chargeback_id: str,
    body: NotesUpdateIn,
    reviewer: Reviewer,
    db: Annotated[Session, Depends(get_db)],
) -> ChargebackDetail:
    chargeback = _get_chargeback(db, chargeback_id)
    _require_editable(chargeback)
    notes = body.notes.strip()
    if notes != chargeback.notes:
        chargeback.notes = notes
        chargeback.notes_updated_by = reviewer.name
        chargeback.notes_updated_at = utcnow()
        record_activity(
            db,
            actor=reviewer,
            record_type=RECORD_TYPE,
            record_id=chargeback.id,
            action="notes_updated",
            previous_status=None,
            new_status=None,
            note=notes or "(notes cleared)",
        )
        db.commit()
    return _detail(db, chargeback)


def _check_upload_allowed(db: Session, chargeback_id: str) -> None:
    chargeback = _get_chargeback(db, chargeback_id)
    _require_editable(chargeback)
    count = db.scalar(select(func.count()).select_from(Attachment).where(Attachment.chargeback_id == chargeback.id))
    if (count or 0) >= MAX_ATTACHMENTS_PER_CASE:
        raise HTTPException(status_code=409, detail=f"At most {MAX_ATTACHMENTS_PER_CASE} files per case.")


def _store_attachment(
    db: Session, chargeback_id: str, reviewer: Identity, filename: str, content_type: str, data: bytes
) -> ChargebackDetail:
    chargeback = _get_chargeback(db, chargeback_id)
    _require_editable(chargeback)
    attachment = Attachment(
        id=f"ATT-{uuid4().hex[:10].upper()}",
        chargeback_id=chargeback.id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        uploaded_by=reviewer.name,
        uploaded_at=utcnow(),
    )
    path = attachment_path(chargeback.id, attachment.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(path)
    db.add(attachment)
    record_activity(
        db,
        actor=reviewer,
        record_type=RECORD_TYPE,
        record_id=chargeback.id,
        action="attachment_uploaded",
        previous_status=None,
        new_status=None,
        note=f"{filename} ({content_type}, {len(data)} bytes)",
    )
    try:
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _detail(db, chargeback)


@router.post("/{chargeback_id}/attachments", response_model=ChargebackDetail, status_code=201)
async def upload_attachment(
    chargeback_id: str,
    request: Request,
    reviewer: Reviewer,
    db: Annotated[Session, Depends(get_db)],
    filename: Annotated[str, Query(min_length=1, max_length=200)],
) -> ChargebackDetail:
    """Raw request body is the file; `Content-Type` is its type and `filename` its display name."""
    await run_in_threadpool(_check_upload_allowed, db, chargeback_id)

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    safe_name = _safe_filename(filename)
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF, PNG, JPEG and plain-text files are accepted.")
    if not safe_name.lower().endswith(ALLOWED_ATTACHMENT_TYPES[content_type]):
        raise HTTPException(status_code=415, detail=f"File name extension does not match type {content_type}.")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than the 5 MB limit.")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="File is larger than the 5 MB limit.")
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")
    if not _content_matches(content_type, bytes(data)):
        raise HTTPException(status_code=415, detail=f"File contents do not look like {content_type}.")
    return await run_in_threadpool(_store_attachment, db, chargeback_id, reviewer, safe_name, content_type, bytes(data))


@router.get("/{chargeback_id}/attachments/{attachment_id}")
def download_attachment(
    chargeback_id: str,
    attachment_id: str,
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.chargeback_id != chargeback_id:
        raise HTTPException(status_code=404, detail=f"Attachment {attachment_id} not found on {chargeback_id}.")
    path = attachment_path(attachment.chargeback_id, attachment.id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Stored file for {attachment_id} is missing.")
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


@router.get("/{chargeback_id}/summary.pdf")
def evidence_summary_pdf(
    chargeback_id: str,
    identity: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    chargeback = _get_chargeback(db, chargeback_id)
    detail = _detail(db, chargeback)
    refund_ids = [r.id for r in detail.refunds]
    refund_activity = list(
        db.scalars(
            select(Activity)
            .where(Activity.record_type == "refund", Activity.record_id.in_(refund_ids))
            .order_by(Activity.created_at, Activity.id)
        )
    ) if refund_ids else []
    case_activity = list(
        db.scalars(
            select(Activity)
            .where(Activity.record_type == RECORD_TYPE, Activity.record_id == chargeback.id)
            .order_by(Activity.created_at, Activity.id)
        )
    )

    pdf = TextPdf(footer=f"{chargeback.id} evidence summary - NOT a submission package - local demo, fictional data")
    pdf.text("Chargeback evidence summary", size=18, bold=True)
    pdf.text("NOT A SUBMISSION PACKAGE", size=12, bold=True)
    pdf.space(4)
    pdf.text(SUMMARY_DISCLAIMER, size=9)
    pdf.text(f"Generated {_format_time(utcnow())} by {identity.name} ({identity.role}).", size=9)

    pdf.heading("Case details")
    status = detail.status + (f" (outcome: {detail.outcome})" if detail.outcome else "")
    for label, value in [
        ("Case", detail.id),
        ("Status", status),
        ("Reason", detail.reason),
        ("Disputed amount", _format_minor(detail.amount_minor, detail.currency)),
        ("Cardholder (as reported)", detail.cardholder_name),
        ("Payment reference", detail.payment_reference),
        ("Evidence deadline (demo assumption)", _format_time(chargeback.evidence_due_at) + (" - OVERDUE" if detail.is_overdue else "")),
        ("Opened", _format_time(chargeback.created_at)),
        ("Closed", _format_time(chargeback.closed_at)),
    ]:
        pdf.text(f"{label}: {value}")

    pdf.heading("Payment and customer")
    if detail.payment:
        p = detail.payment
        pdf.text(f"Payment {p.reference}: {_format_minor(p.amount_minor, p.currency)}, card ending {p.card_last4}, "
                 f"captured {_format_time(p.captured_at.replace(tzinfo=None))}. {p.description}")
    if detail.customer:
        c = detail.customer
        pdf.text(f"Customer: {c.customer_name} (KYC case {c.kyc_case_id}, status {c.kyc_status}, risk {c.risk_label}). "
                 f"Identity check: {c.check_summary}")
    if detail.missing_information:
        pdf.text("Missing information:", bold=True)
        for item in detail.missing_information:
            pdf.text(f"- {item}", indent=10)

    pdf.heading("Transaction and refund history")
    if not detail.refunds:
        pdf.text("No refund exceptions recorded for this payment.")
    for refund in detail.refunds:
        pdf.text(f"{refund.id}: {_format_minor(refund.amount_minor, refund.currency)}, status {refund.status}, "
                 f"created {_format_time(refund.created_at.replace(tzinfo=None))}. {refund.failure_reason}", bold=True)
        entries = [a for a in refund_activity if a.record_id == refund.id]
        if not entries:
            pdf.text("No refund activity recorded.", indent=10)
        for entry in entries:
            change = f" {entry.previous_status or '-'} -> {entry.new_status}" if entry.new_status else ""
            pdf.text(f"{_format_time(entry.created_at)}  {entry.action} by {entry.actor_name}{change}"
                     + (f": {entry.note}" if entry.note else ""), size=9, indent=10)

    pdf.heading("Evidence checklist (demo assumptions)")
    for item in detail.checklist:
        mark = "[x]" if item.done else "[ ]"
        by = f" - {item.updated_by}, {_format_time(item.updated_at.replace(tzinfo=None))}" if item.done and item.updated_at else ""
        pdf.text(f"{mark} {item.label}{by}")

    pdf.heading("Case notes")
    pdf.text(detail.notes or "No case notes.")

    pdf.heading("Attachment inventory (files are not included in this summary)")
    if not detail.attachments:
        pdf.text("No evidence files uploaded.")
    for att in detail.attachments:
        pdf.text(f"{att.filename} - {att.content_type}, {att.size_bytes} bytes, uploaded by {att.uploaded_by} "
                 f"{_format_time(att.uploaded_at.replace(tzinfo=None))}")
        pdf.text(f"sha256 {att.sha256}", size=8, indent=10)

    pdf.heading("Case activity")
    if not case_activity:
        pdf.text("No activity recorded.")
    for entry in case_activity:
        change = f" {entry.previous_status or '-'} -> {entry.new_status}" if entry.new_status else ""
        pdf.text(f"{_format_time(entry.created_at)}  {entry.action} by {entry.actor_name}{change}"
                 + (f": {entry.note}" if entry.note else ""), size=9)

    return Response(
        content=pdf.render(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{chargeback.id}-evidence-summary.pdf"',
            "Cache-Control": "no-store",
        },
    )
