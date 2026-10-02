"""Seed fictional demo data.

    python -m app.seed           # seed an empty database (refuses if data exists)
    python -m app.seed --reset   # drop all tables, recreate, and seed
"""

import argparse
import sys
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, create_tables, engine
from .kyc import KycCase
from .refunds import RefundException

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
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop all tables before seeding")
    args = parser.parse_args()

    if args.reset:
        Base.metadata.drop_all(engine)
    create_tables()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(KycCase)):
            print("Database already has data; use --reset to wipe and reseed.", file=sys.stderr)
            return 1
        seed(db)
    print(f"Seeded {len(KYC_CASES)} KYC cases and {len(REFUND_EXCEPTIONS)} refund exceptions into {engine.url}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
