"""Seed fictional demo data.

    python -m app.seed           # seed an empty database (refuses if data exists)
    python -m app.seed --reset   # drop all tables, delete stored attachments, recreate, and seed
"""

import argparse
import sys
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .activity import new_request_id, record_activity, set_request_id
from .auth import SYSTEM
from .chargebacks import Chargeback, ChecklistItem, checklist_for_reason, clear_attachment_files
from .db import Base, SessionLocal, create_tables, engine, utcnow
from .kyc import KycCase
from .payments import Payment
from .refunds import RefundException
from .tasks import find_task
from .work import sync_all_tasks

BASE_TIME = datetime(2026, 9, 28, 9, 0, 0)

KYC_CASES = [
    ("KYC-1001", "Ada Fictional", "low", "Document and selfie match; address verified.", "pending_review"),
    ("KYC-1002", "Bram Example", "high", "Name partially matches a watchlist entry; manual check needed.", "pending_review"),
    ("KYC-1003", "Chen Sample", "medium", "ID document glare; face match score 0.81.", "pending_review"),
    ("KYC-1004", "Dana Placeholder", "low", "All automated checks passed.", "approved"),
    ("KYC-1005", "Eli Testcase", "medium", "Proof of address older than 90 days.", "awaiting_information"),
    ("KYC-1006", "Farah Mock", "high", "Device fingerprint linked to 3 prior applications.", "pending_review"),
    ("KYC-1007", "Gus Demo", "low", "Date of birth mismatch between form and document.", "pending_review"),
    ("KYC-1008", "Hana Fixture", "high", "Document template not recognised.", "rejected"),
    ("KYC-1009", "Ivo Stub", "medium", "Phone number recently ported; email domain new.", "pending_review"),
    ("KYC-1010", "Jun Dummy", "low", "Selfie liveness retry succeeded.", "awaiting_information"),
]

REFUND_EXCEPTIONS = [
    ("RFX-SEED0001", "evt_demo_0001", "pay_demo_A1001", 2599, "USD", "Destination card account closed.", "open"),
    ("RFX-SEED0002", "evt_demo_0002", "pay_demo_B2002", 120000, "EUR", "Issuer declined refund: suspected fraud hold.", "escalated"),
    ("RFX-SEED0003", "evt_demo_0003", "pay_demo_C3003", 499, "GBP", "Refund exceeds original capture amount.", "resolved"),
]

# Payments link the refund and chargeback references to KYC customers (None = no known customer).
PAYMENTS = [
    ("pay_demo_A1001", "KYC-1004", 2599, "USD", "Annual plan renewal"),
    ("pay_demo_B2002", "KYC-1002", 120000, "EUR", "Laptop order #B-2002"),
    ("pay_demo_C3003", "KYC-1001", 499, "GBP", "E-book purchase"),
    ("pay_demo_D4004", "KYC-1006", 8900, "USD", "Headphones order #D-4004"),
    ("pay_demo_E5005", None, 15000, "USD", "Gift card bundle"),
]

# Evidence deadlines are relative to seeding time (in days) so the demo always shows overdue and upcoming cases.
# CBK-2006 references a payment that is deliberately absent from PAYMENTS to show missing linked data.
CHARGEBACKS = [
    ("CBK-2001", "pay_demo_A1001", "Dana Placeholder", 2599, "USD", "credit_not_processed", -2, "collecting_evidence", None),
    ("CBK-2002", "pay_demo_B2002", "Bram Example", 120000, "EUR", "fraudulent", 3, "open", None),
    ("CBK-2003", "pay_demo_C3003", "Ada Fictional", 499, "GBP", "duplicate_charge", 6, "ready_for_review", None),
    ("CBK-2004", "pay_demo_D4004", "Farah Mock", 8900, "USD", "product_not_received", 1, "collecting_evidence", None),
    ("CBK-2005", "pay_demo_E5005", "Kai Unlinked", 15000, "USD", "fraudulent", -1, "open", None),
    ("CBK-2006", "pay_demo_F6006", "Lea Missing", 4200, "EUR", "product_not_received", -10, "closed", "lost"),
]
CHECKLIST_DONE = {
    "CBK-2001": {"receipt"},
    "CBK-2003": {"receipt", "distinct_charges", "refund_records"},
    "CBK-2004": {"receipt", "tracking"},
}


# Demo work assignments: (app, record, assignee, deadline in days from seeding or None, priority or None).
# CBK-2003 is left unassigned for the README walkthrough.
TASK_SETUP = [
    ("kyc", "KYC-1001", "reviewer", 1, None),
    ("kyc", "KYC-1002", "reviewer2", 2, "urgent"),
    ("refund", "RFX-SEED0002", "reviewer2", -1, None),
    ("chargeback", "CBK-2001", "reviewer", None, None),
    ("chargeback", "CBK-2004", "reviewer2", None, None),
]


def seed(db: Session) -> None:
    for index, (case_id, name, risk, summary, status) in enumerate(KYC_CASES):
        db.add(
            KycCase(
                id=case_id,
                customer_name=name,
                submitted_at=BASE_TIME + timedelta(minutes=37 * index),
                risk_label=risk,
                check_summary=summary,
                status=status,
            )
        )
    for index, (refund_id, event_id, payment_ref, amount, currency, reason, status) in enumerate(REFUND_EXCEPTIONS):
        db.add(
            RefundException(
                id=refund_id,
                external_event_id=event_id,
                payment_reference=payment_ref,
                amount_minor=amount,
                currency=currency,
                failure_reason=reason,
                status=status,
                created_at=BASE_TIME + timedelta(hours=index),
            )
        )
    db.flush()
    for index, (reference, kyc_id, amount, currency, description) in enumerate(PAYMENTS):
        db.add(
            Payment(
                reference=reference,
                customer_kyc_id=kyc_id,
                amount_minor=amount,
                currency=currency,
                captured_at=BASE_TIME - timedelta(days=20 - index),
                card_last4=f"{4242 + index * 1111:04d}"[-4:],
                description=description,
            )
        )
    now = utcnow().replace(microsecond=0)
    for case_id, reference, name, amount, currency, reason, due_days, status, outcome in CHARGEBACKS:
        db.add(
            Chargeback(
                id=case_id,
                payment_reference=reference,
                cardholder_name=name,
                amount_minor=amount,
                currency=currency,
                reason=reason,
                evidence_due_at=now + timedelta(days=due_days),
                status=status,
                outcome=outcome,
                notes="",
                created_at=now - timedelta(days=14),
                closed_at=now - timedelta(days=11) if status == "closed" else None,
            )
        )
        done = CHECKLIST_DONE.get(case_id, set())
        for position, (key, label) in enumerate(checklist_for_reason(reason)):
            db.add(
                ChecklistItem(
                    chargeback_id=case_id,
                    item_key=key,
                    label=label,
                    position=position,
                    done=key in done,
                    updated_by="Seed data" if key in done else None,
                    updated_at=now - timedelta(days=1) if key in done else None,
                )
            )
    db.flush()
    set_request_id(new_request_id("seed"))
    sync_all_tasks(db)
    for app, record_id, assignee, due_days, priority in TASK_SETUP:
        task = find_task(db, app, record_id)
        assert task is not None and task.state == "active", f"seed task missing for {record_id}"
        task.assignee_id = assignee
        if due_days is not None:
            task.due_at = now + timedelta(days=due_days)
        if priority is not None:
            task.priority = priority
        record_activity(
            db,
            actor=SYSTEM,
            record_type=app,
            record_id=record_id,
            action="task_assigned",
            category="work",
            task_id=task.id,
            before={"assignee_id": None},
            after={"assignee_id": assignee, "priority": task.priority, "due_at": task.due_at.isoformat() + "Z" if task.due_at else None},
            note="Seed data",
        )
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop all tables before seeding")
    args = parser.parse_args()

    if args.reset:
        Base.metadata.drop_all(engine)
        clear_attachment_files()
    create_tables()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(KycCase)):
            print("Database already has data; use --reset to wipe and reseed.", file=sys.stderr)
            return 1
        seed(db)
    print(
        f"Seeded {len(KYC_CASES)} KYC cases, {len(REFUND_EXCEPTIONS)} refund exceptions, {len(PAYMENTS)} payments "
        f"and {len(CHARGEBACKS)} chargebacks into {engine.url}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
