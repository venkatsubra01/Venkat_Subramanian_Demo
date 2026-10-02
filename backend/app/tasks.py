"""Shared work tasks: one review task per actionable source case.

A task carries assignment, an optional operational deadline and a priority. It does not have
its own editable workflow: `sync_task()` derives active/completed from the source case's status,
and is called by each source app's handlers in the same transaction as the status change.
"""

from datetime import datetime
from typing import Literal

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .activity import record_activity
from .auth import SYSTEM
from .db import Base, UTCDateTime, utcnow

SourceApp = Literal["kyc", "refund", "chargeback"]
Priority = Literal["low", "normal", "high", "urgent"]
PRIORITIES: tuple[str, ...] = ("urgent", "high", "normal", "low")


class WorkTask(Base):
    __tablename__ = "work_tasks"
    # One task row per source case; reopening reactivates it, so duplicates cannot exist.
    __table_args__ = (UniqueConstraint("source_app", "source_id", name="uq_work_task_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_app: Mapped[str] = mapped_column(String(16), index=True)
    source_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="review")
    state: Mapped[str] = mapped_column(String(16), index=True)  # active | completed (derived)
    assignee_id: Mapped[str | None] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    due_at: Mapped[UTCDateTime | None]
    created_at: Mapped[UTCDateTime] = mapped_column(default=utcnow)
    updated_at: Mapped[UTCDateTime] = mapped_column(default=utcnow)
    completed_at: Mapped[UTCDateTime | None]


def find_task(db: Session, source_app: str, source_id: str) -> WorkTask | None:
    return db.scalar(select(WorkTask).where(WorkTask.source_app == source_app, WorkTask.source_id == source_id))


def is_overdue(task: WorkTask, now: datetime | None = None) -> bool:
    return task.state == "active" and task.due_at is not None and task.due_at < (now or utcnow())


def sync_task(
    db: Session,
    *,
    source_app: SourceApp,
    source_id: str,
    source_status: str,
    actionable: bool,
    priority: Priority = "normal",
    due_at: datetime | None = None,
) -> WorkTask | None:
    """Create, complete or reactivate the case's task to match its source status.

    Idempotent. `priority`/`due_at` are only defaults for a newly created task. Adds rows to the
    caller's transaction; the caller commits.
    """
    task = find_task(db, source_app, source_id)
    now = utcnow()
    if task is None:
        if not actionable:
            return None
        task = WorkTask(
            source_app=source_app,
            source_id=source_id,
            kind="review",
            state="active",
            priority=priority,
            due_at=due_at,
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.flush()
        _record(db, task, "task_created", None, {"state": "active", "priority": priority, "due_at": _iso(due_at)},
                f"Review task opened for {source_status} case.")
    elif actionable and task.state == "completed":
        task.state, task.completed_at, task.updated_at = "active", None, now
        _record(db, task, "task_reactivated", {"state": "completed"}, {"state": "active"},
                f"Case reopened ({source_status}).")
    elif not actionable and task.state == "active":
        task.state, task.completed_at, task.updated_at = "completed", now, now
        _record(db, task, "task_completed", {"state": "active"}, {"state": "completed"},
                f"Case reached {source_status}.")
    return task


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _record(
    db: Session,
    task: WorkTask,
    action: str,
    before: dict[str, str | None] | None,
    after: dict[str, str | None],
    note: str,
) -> None:
    record_activity(
        db,
        actor=SYSTEM,
        record_type=task.source_app,
        record_id=task.source_id,
        action=action,
        category="work",
        task_id=task.id,
        before=before,
        after=after,
        note=note,
    )
