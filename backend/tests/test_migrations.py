"""Upgrade an existing pre-Work-Manager database without losing data."""

from sqlalchemy import func, select, text

from app.activity import Activity
from app.db import SessionLocal, engine
from app.kyc import KycCase
from app.migrations import upgrade
from app.tasks import WorkTask


def _make_legacy_schema() -> None:
    """Strip the tables and columns this extension added, as an older database would look."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE work_tasks"))
        conn.execute(text("DROP TABLE approval_requests"))
        conn.execute(text("DELETE FROM activity"))
        conn.execute(text("DROP INDEX ix_activity_category"))
        conn.execute(text("DROP INDEX ix_activity_request_id"))
        for column in ("category", "request_id", "task_id", "approval_id", "before_values", "after_values"):
            conn.execute(text(f'ALTER TABLE activity DROP COLUMN "{column}"'))
        conn.execute(text("ALTER TABLE chargebacks DROP COLUMN evidence_version"))
        conn.execute(text("UPDATE kyc_cases SET status = 'approved' WHERE id = 'KYC-1001'"))
        conn.execute(text(
            "INSERT INTO activity (record_type, record_id, actor_id, actor_name, action, previous_status, "
            "new_status, note, created_at) VALUES ('kyc', 'KYC-1001', 'reviewer', 'Riley Reviewer', 'approve', "
            "'pending_review', 'approved', 'legacy decision', '2026-09-29 10:00:00')"
        ))


def _columns(table: str) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info('{table}')"))}


def test_upgrade_adds_columns_keeps_data_and_backfills_tasks(reviewer):
    _make_legacy_schema()
    assert "category" not in _columns("activity")

    applied = upgrade()
    assert "added activity.category" in applied and "added chargebacks.evidence_version" in applied
    assert {"category", "request_id", "task_id", "approval_id", "before_values", "after_values"} <= _columns("activity")

    with SessionLocal() as db:
        assert db.get(KycCase, "KYC-1001").status == "approved"
        legacy = db.scalars(select(Activity).where(Activity.note == "legacy decision")).one()
        assert legacy.category == "case" and legacy.request_id is None
        active = db.scalar(select(func.count()).select_from(WorkTask).where(WorkTask.state == "active"))
        assert active == 14  # 15 seeded actionable cases minus KYC-1001, decided before the upgrade
        assert db.scalar(select(func.count()).select_from(WorkTask).where(WorkTask.source_id == "KYC-1001")) == 0
        assert db.scalar(text("SELECT evidence_version FROM chargebacks WHERE id = 'CBK-2003'")) == 1

    assert upgrade() == []  # second run changes nothing

    history = reviewer.get("/api/activity", params={"record_type": "kyc", "record_id": "KYC-1001"}).json()
    assert [e["note"] for e in history] == ["legacy decision"]
    assert reviewer.get("/api/chargebacks/CBK-2003").json()["evidence_version"] == 1
