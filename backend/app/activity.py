from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import CurrentUser, Identity
from .db import Base, UTCDateTime, get_db, utcnow


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


def record_activity(
    db: Session,
    *,
    actor: Identity,
    record_type: str,
    record_id: str,
    action: str,
    previous_status: str | None,
    new_status: str | None,
    note: str | None = None,
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
    )
    db.add(entry)
    return entry


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


router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[ActivityOut])
def list_activity(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    record_type: Annotated[str | None, Query(pattern=r"^[a-z_]{1,32}$")] = None,
    record_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[Activity]:
    query = select(Activity)
    if record_type is not None:
        query = query.where(Activity.record_type == record_type)
    if record_id is not None:
        query = query.where(Activity.record_id == record_id)
    query = query.order_by(Activity.created_at.desc(), Activity.id.desc()).limit(limit)
    return list(db.scalars(query))
