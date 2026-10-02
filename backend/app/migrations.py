"""Non-destructive schema upgrade for existing local databases.

`create_all()` creates missing tables but never alters existing ones, so columns added after a
database was first created are added here with `ALTER TABLE ... ADD COLUMN`. Each step checks
the live schema first, so running it repeatedly is safe. Nothing is dropped or reseeded.

Run explicitly with `python -m app.migrations`; the API also runs it at startup.
"""

import sys

from sqlalchemy import Engine, text

from .activity import new_request_id, reset_request_id, set_request_id
from .db import SessionLocal, create_tables, engine
from .work import sync_all_tasks

# (table, column, DDL type/default). Existing rows get the default.
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("activity", "category", "VARCHAR(16) NOT NULL DEFAULT 'case'"),
    ("activity", "request_id", "VARCHAR(64)"),
    ("activity", "task_id", "INTEGER"),
    ("activity", "approval_id", "INTEGER"),
    ("activity", "before_values", "JSON"),
    ("activity", "after_values", "JSON"),
    ("chargebacks", "evidence_version", "INTEGER NOT NULL DEFAULT 1"),
]
ADDED_INDEXES: list[tuple[str, str, str]] = [
    ("ix_activity_category", "activity", "category"),
    ("ix_activity_request_id", "activity", "request_id"),
]


def upgrade(engine_: Engine = engine) -> list[str]:
    """Bring an existing database up to date and create tasks for actionable cases."""
    create_tables()
    applied: list[str] = []
    with engine_.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info('{table}')"))}
            if column not in existing:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
                applied.append(f"added {table}.{column}")
        for name, table, column in ADDED_INDEXES:
            conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ("{column}")'))
    token = set_request_id(new_request_id("upgrade"))
    try:
        with SessionLocal() as db:
            result = sync_all_tasks(db)
            db.commit()
    finally:
        reset_request_id(token)
    if result.created or result.completed or result.reactivated:
        applied.append(
            f"tasks: {result.created} created, {result.completed} completed, {result.reactivated} reactivated"
        )
    return applied


def main() -> int:
    applied = upgrade()
    print("\n".join(applied) if applied else "Database already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
