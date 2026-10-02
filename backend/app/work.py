"""Work Manager and approval inbox routes.

Supervisors see and manage every task; employees see the tasks assigned to them. Managing a
task changes only assignment, deadline and priority. Completion comes from the source case
(see `tasks.sync_task`), and assignment grants no access: case routes keep their own checks.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from .activity import record_activity
from .approvals import ApprovalOut, ApprovalRequest
from .auth import IDENTITIES, CurrentUser, Supervisor, assignable_identities
from .chargebacks import Chargeback
from .chargebacks import sync_case_task as sync_chargeback_task
from .db import UTCDateTime, get_db, utcnow
from .kyc import KycCase
from .kyc import sync_case_task as sync_kyc_task
from .refunds import RefundException
from .refunds import sync_record_task as sync_refund_task
from .tasks import PRIORITIES, Priority, SourceApp, WorkTask, find_task, is_overdue

APP_LABELS: dict[str, str] = {"kyc": "KYC review", "refund": "Refund exception", "chargeback": "Chargeback"}


class TaskOut(BaseModel):
    id: int
    source_app: str
    source_id: str
    source_label: str
    source_status: str
    kind: str
    state: str
    assignee_id: str | None
    assignee_name: str | None
    priority: str
    due_at: UTCDateTime | None
    is_overdue: bool
    created_at: UTCDateTime
    updated_at: UTCDateTime
    completed_at: UTCDateTime | None


class TaskListOut(BaseModel):
    items: list[TaskOut]
    total: int
    overdue_count: int
    unassigned_count: int


class AssigneeOut(BaseModel):
    id: str
    name: str
    role: str


class TaskUpdateIn(BaseModel):
    """Only fields that are present are changed; send `"due_at": null` to clear the deadline."""

    assignee_id: str | None = None
    priority: Priority | None = None
    due_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("due_at")
    @classmethod
    def to_naive_utc(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @model_validator(mode="after")
    def something_to_change(self) -> "TaskUpdateIn":
        self.reason = self.reason.strip() if self.reason else None
        if not ({"assignee_id", "priority", "due_at"} & self.model_fields_set):
            raise ValueError("Provide assignee_id, priority or due_at.")
        if "priority" in self.model_fields_set and self.priority is None:
            raise ValueError("Priority cannot be empty.")
        return self


class SyncResult(BaseModel):
    created: int
    completed: int
    reactivated: int


def _source_summaries(db: Session, tasks: list[WorkTask]) -> dict[tuple[str, str], tuple[str, str]]:
    """(app, id) -> (label, status). Explicit per-app lookups; no registry."""
    ids: dict[str, list[str]] = {"kyc": [], "refund": [], "chargeback": []}
    for task in tasks:
        ids[task.source_app].append(task.source_id)
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for kyc in db.scalars(select(KycCase).where(KycCase.id.in_(ids["kyc"]))):
        out[("kyc", kyc.id)] = (f"{kyc.customer_name} · {kyc.risk_label} risk", kyc.status)
    for refund in db.scalars(select(RefundException).where(RefundException.id.in_(ids["refund"]))):
        out[("refund", refund.id)] = (
            f"{refund.payment_reference} · {refund.amount_minor / 100:,.2f} {refund.currency}",
            refund.status,
        )
    for cb in db.scalars(select(Chargeback).where(Chargeback.id.in_(ids["chargeback"]))):
        out[("chargeback", cb.id)] = (
            f"{cb.cardholder_name} · {cb.amount_minor / 100:,.2f} {cb.currency}",
            cb.status,
        )
    return out


def _task_out(task: WorkTask, summary: tuple[str, str] | None, now: datetime) -> TaskOut:
    assignee = IDENTITIES.get(task.assignee_id) if task.assignee_id else None
    label, status = summary or (f"{task.source_id} (source record missing)", "unknown")
    return TaskOut(
        id=task.id,
        source_app=task.source_app,
        source_id=task.source_id,
        source_label=label,
        source_status=status,
        kind=task.kind,
        state=task.state,
        assignee_id=task.assignee_id,
        assignee_name=assignee.name if assignee else None,
        priority=task.priority,
        due_at=task.due_at,
        is_overdue=is_overdue(task, now),
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


def _task_list(db: Session, tasks: list[WorkTask]) -> TaskListOut:
    now = utcnow()
    summaries = _source_summaries(db, tasks)
    items = [_task_out(t, summaries.get((t.source_app, t.source_id)), now) for t in tasks]
    return TaskListOut(
        items=items,
        total=len(items),
        overdue_count=sum(1 for i in items if i.is_overdue),
        unassigned_count=sum(1 for i in items if i.state == "active" and i.assignee_id is None),
    )


_PRIORITY_RANK = case({p: i for i, p in enumerate(PRIORITIES)}, value=WorkTask.priority, else_=len(PRIORITIES))
_ORDER = (WorkTask.due_at.is_(None), WorkTask.due_at, _PRIORITY_RANK, WorkTask.id)


def sync_all_tasks(db: Session) -> SyncResult:
    """Make tasks match every source case. Idempotent; used by seeding, upgrades and the sync route."""

    states_before = {t.id: t.state for t in db.scalars(select(WorkTask))}
    for kyc in db.scalars(select(KycCase)):
        sync_kyc_task(db, kyc)
    for refund in db.scalars(select(RefundException)):
        sync_refund_task(db, refund)
    for chargeback in db.scalars(select(Chargeback)):
        sync_chargeback_task(db, chargeback)
    db.flush()
    after_tasks = list(db.scalars(select(WorkTask)))
    created = len(after_tasks) - len(states_before)
    completed = sum(1 for t in after_tasks if states_before.get(t.id) == "active" and t.state == "completed")
    reactivated = sum(1 for t in after_tasks if states_before.get(t.id) == "completed" and t.state == "active")
    return SyncResult(created=created, completed=completed, reactivated=reactivated)


router = APIRouter(prefix="/api/work", tags=["work"])


@router.get("/tasks", response_model=TaskListOut)
def list_tasks(
    _: Supervisor,
    db: Annotated[Session, Depends(get_db)],
    app: SourceApp | None = None,
    assignee_id: Annotated[str | None, Query(pattern=r"^[a-z0-9_]{1,32}$")] = None,
    priority: Priority | None = None,
    unassigned: bool = False,
    overdue: bool = False,
    state: Literal["active", "completed", "all"] = "active",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> TaskListOut:
    query = select(WorkTask)
    if state != "all":
        query = query.where(WorkTask.state == state)
    if app is not None:
        query = query.where(WorkTask.source_app == app)
    if assignee_id is not None:
        query = query.where(WorkTask.assignee_id == assignee_id)
    if unassigned:
        query = query.where(WorkTask.assignee_id.is_(None))
    if priority is not None:
        query = query.where(WorkTask.priority == priority)
    if overdue:
        query = query.where(WorkTask.state == "active", WorkTask.due_at.is_not(None), WorkTask.due_at < utcnow())
    return _task_list(db, list(db.scalars(query.order_by(*_ORDER).limit(limit))))


@router.get("/mine", response_model=TaskListOut)
def my_work(
    identity: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    state: Literal["active", "completed", "all"] = "active",
) -> TaskListOut:
    query = select(WorkTask).where(WorkTask.assignee_id == identity.id)
    if state != "all":
        query = query.where(WorkTask.state == state)
    return _task_list(db, list(db.scalars(query.order_by(*_ORDER).limit(200))))


@router.get("/assignees", response_model=list[AssigneeOut])
def list_assignees(_: CurrentUser) -> list[AssigneeOut]:
    return [AssigneeOut(id=i.id, name=i.name, role=i.role) for i in assignable_identities()]


@router.get("/by-source/{source_app}/{source_id}", response_model=TaskOut | None)
def task_for_source(
    source_app: SourceApp, source_id: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> TaskOut | None:
    task = find_task(db, source_app, source_id)
    if task is None:
        return None
    return _task_list(db, [task]).items[0]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    body: TaskUpdateIn,
    supervisor: Supervisor,
    db: Annotated[Session, Depends(get_db)],
) -> TaskOut:
    task = db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")
    if task.state != "active":
        raise HTTPException(status_code=409, detail=f"Task {task_id} is completed; its case is closed.")
    changes: list[tuple[str, dict[str, str | None], dict[str, str | None]]] = []
    if "assignee_id" in body.model_fields_set and body.assignee_id != task.assignee_id:
        if body.assignee_id is not None and body.assignee_id not in {i.id for i in assignable_identities()}:
            raise HTTPException(status_code=422, detail=f"'{body.assignee_id}' is not an eligible employee.")
        action = "task_unassigned" if body.assignee_id is None else (
            "task_assigned" if task.assignee_id is None else "task_reassigned"
        )
        changes.append((action, {"assignee_id": task.assignee_id}, {"assignee_id": body.assignee_id}))
        task.assignee_id = body.assignee_id
    if "priority" in body.model_fields_set and body.priority is not None and body.priority != task.priority:
        changes.append(("task_priority_changed", {"priority": task.priority}, {"priority": body.priority}))
        task.priority = body.priority
    if "due_at" in body.model_fields_set and body.due_at != task.due_at:
        changes.append(("task_deadline_changed", {"due_at": _iso(task.due_at)}, {"due_at": _iso(body.due_at)}))
        task.due_at = body.due_at
    if changes:
        task.updated_at = utcnow()
        for action, before, after in changes:
            record_activity(
                db,
                actor=supervisor,
                record_type=task.source_app,
                record_id=task.source_id,
                action=action,
                category="work",
                task_id=task.id,
                before=before,
                after=after,
                note=body.reason,
            )
        db.commit()
    return _task_list(db, [task]).items[0]


@router.post("/sync", response_model=SyncResult)
def sync_tasks(_: Supervisor, db: Annotated[Session, Depends(get_db)]) -> SyncResult:
    """Create missing tasks and repair task state from source cases. Safe to repeat."""
    result = sync_all_tasks(db)
    db.commit()
    return result


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


# ---------------------------------------------------------------- approval inbox


class ApprovalInboxItem(ApprovalOut):
    source_label: str
    source_status: str


class ApprovalInboxOut(BaseModel):
    items: list[ApprovalInboxItem]
    state_counts: dict[str, int]


approvals_router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@approvals_router.get("", response_model=ApprovalInboxOut)
def approval_inbox(
    _: Supervisor,
    db: Annotated[Session, Depends(get_db)],
    state: Literal["pending", "approved", "returned", "invalidated", "all"] = "pending",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ApprovalInboxOut:
    """Coordinates approvals across apps. Deciding happens on each app's own endpoints."""
    query = select(ApprovalRequest)
    if state != "all":
        query = query.where(ApprovalRequest.state == state)
    requests = list(db.scalars(query.order_by(ApprovalRequest.requested_at.desc(), ApprovalRequest.id.desc()).limit(limit)))
    chargeback_ids = [r.source_id for r in requests if r.source_app == "chargeback"]
    labels = {
        ("chargeback", cb.id): (f"{cb.cardholder_name} · {cb.amount_minor / 100:,.2f} {cb.currency}", cb.status)
        for cb in db.scalars(select(Chargeback).where(Chargeback.id.in_(chargeback_ids)))
    }
    counts: dict[str, int] = {s: 0 for s in ("pending", "approved", "returned", "invalidated")}
    for request_state in db.scalars(select(ApprovalRequest.state)):
        counts[request_state] = counts.get(request_state, 0) + 1
    items = []
    for r in requests:
        label, status = labels.get((r.source_app, r.source_id), (r.source_id, "unknown"))
        items.append(ApprovalInboxItem(**ApprovalOut.model_validate(r).model_dump(), source_label=label, source_status=status))
    return ApprovalInboxOut(items=items, state_counts=counts)
