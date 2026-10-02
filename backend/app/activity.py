"""Shared activity / audit storage.

Application-level append-only: there are no update or delete endpoints, and ORM updates or
deletes of `Activity` rows raise. Anyone with database access can still change rows; this is
not tamper-proof storage.
"""

from contextvars import ContextVar
from datetime import timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, String, Text, event, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import CurrentUser, Identity, Supervisor
from .db import Base, UTCDateTime, get_db, utcnow

# "case": workflow decisions, evidence and approvals; "work": task lifecycle and assignment;
# "access": sensitive views, downloads and exports.
Category = Literal["case", "work", "access"]
JsonValues = dict[str, str | int | bool | None]

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id(prefix: str = "req") -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def set_request_id(value: str):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def current_request_id() -> str:
    """The HTTP request's id (set by middleware), or a fresh id for work outside a request."""
    value = _request_id.get()
    if value is None:
        value = new_request_id("sys")
        _request_id.set(value)
    return value


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(32), index=True)
    record_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(32))
    actor_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(64))
    previous_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[UTCDateTime] = mapped_column(default=utcnow)
    category: Mapped[str] = mapped_column(String(16), default="case", server_default="case", index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    task_id: Mapped[int | None]
    approval_id: Mapped[int | None]
    before_values: Mapped[JsonValues | None] = mapped_column(JSON)
    after_values: Mapped[JsonValues | None] = mapped_column(JSON)


class AppendOnlyViolation(RuntimeError):
    pass


@event.listens_for(Activity, "before_update")
def _refuse_update(*_: object) -> None:
    raise AppendOnlyViolation("Activity entries are append-only; record a correction as a new entry.")


@event.listens_for(Activity, "before_delete")
def _refuse_delete(*_: object) -> None:
    raise AppendOnlyViolation("Activity entries are append-only and cannot be deleted.")


def record_activity(
    db: Session,
    *,
    actor: Identity,
    record_type: str,
    record_id: str,
    action: str,
    previous_status: str | None = None,
    new_status: str | None = None,
    note: str | None = None,
    category: Category = "case",
    task_id: int | None = None,
    approval_id: int | None = None,
    before: JsonValues | None = None,
    after: JsonValues | None = None,
) -> Activity:
    """Add an activity row to the caller's transaction. The caller commits."""
    entry = Activity(
        record_type=record_type,
        record_id=record_id,
        actor_id=actor.id,
        actor_name=actor.name,
        action=action,
        previous_status=previous_status,
        new_status=new_status,
        note=note,
        created_at=utcnow(),
        category=category,
        request_id=current_request_id(),
        task_id=task_id,
        approval_id=approval_id,
        before_values=before,
        after_values=after,
    )
    db.add(entry)
    return entry


VIEW_DEDUPE_WINDOW = timedelta(minutes=10)


def record_sensitive_view(db: Session, *, actor: Identity, record_type: str, record_id: str) -> None:
    """Log a view of a sensitive record at most once per actor and record per window, then commit.

    Detail pages reload after every change; logging each reload would bury real events.
    """
    since = utcnow() - VIEW_DEDUPE_WINDOW
    recent = db.scalar(
        select(Activity.id).where(
            Activity.record_type == record_type,
            Activity.record_id == record_id,
            Activity.actor_id == actor.id,
            Activity.action == "record_viewed",
            Activity.created_at >= since,
        ).limit(1)
    )
    if recent is None:
        record_activity(
            db, actor=actor, record_type=record_type, record_id=record_id, action="record_viewed", category="access"
        )
        db.commit()


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    record_type: str
    record_id: str
    actor_id: str
    actor_name: str
    action: str
    previous_status: str | None
    new_status: str | None
    note: str | None
    created_at: UTCDateTime
    category: str
    request_id: str | None
    task_id: int | None
    approval_id: int | None
    before_values: JsonValues | None
    after_values: JsonValues | None


router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[ActivityOut])
def list_activity(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    record_type: Annotated[str | None, Query(pattern=r"^[a-z_]{1,32}$")] = None,
    record_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    category: Annotated[list[Category] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[Activity]:
    """Per-record history. Defaults to case events (decisions, evidence, approvals); pass
    `category` (repeatable) to include work-management and access events."""
    query = select(Activity).where(Activity.category.in_(category or ["case"]))
    if record_type is not None:
        query = query.where(Activity.record_type == record_type)
    if record_id is not None:
        query = query.where(Activity.record_id == record_id)
    query = query.order_by(Activity.created_at.desc(), Activity.id.desc()).limit(limit)
    return list(db.scalars(query))


class AuditPage(BaseModel):
    items: list[ActivityOut]
    total: int
    page: int
    page_size: int


audit_router = APIRouter(prefix="/api/audit", tags=["audit"])


@audit_router.get("", response_model=AuditPage)
def audit_log(
    _: Supervisor,
    db: Annotated[Session, Depends(get_db)],
    app: Annotated[str | None, Query(pattern=r"^[a-z_]{1,32}$")] = None,
    record_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    actor_id: Annotated[str | None, Query(pattern=r"^[a-z0-9_]{1,32}$")] = None,
    action: Annotated[str | None, Query(pattern=r"^[a-z_]{1,64}$")] = None,
    category: Category | None = None,
    request_id: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,64}$")] = None,
    task_id: int | None = None,
    approval_id: int | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AuditPage:
    filters = []
    if app is not None:
        filters.append(Activity.record_type == app)
    if record_id is not None:
        filters.append(Activity.record_id == record_id)
    if actor_id is not None:
        filters.append(Activity.actor_id == actor_id)
    if action is not None:
        filters.append(Activity.action == action)
    if category is not None:
        filters.append(Activity.category == category)
    if request_id is not None:
        filters.append(Activity.request_id == request_id)
    if task_id is not None:
        filters.append(Activity.task_id == task_id)
    if approval_id is not None:
        filters.append(Activity.approval_id == approval_id)
    total = db.scalar(select(func.count()).select_from(Activity).where(*filters)) or 0
    query = (
        select(Activity)
        .where(*filters)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return AuditPage(
        items=[ActivityOut.model_validate(a) for a in db.scalars(query)], total=total, page=page, page_size=page_size
    )
