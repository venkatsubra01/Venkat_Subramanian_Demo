import pytest
from sqlalchemy import select

from app.activity import Activity, AppendOnlyViolation
from app.db import SessionLocal
from app.main import app


def test_audit_log_is_supervisor_only(viewer, reviewer, supervisor2):
    assert viewer.get("/api/audit").status_code == 403
    assert reviewer.get("/api/audit").status_code == 403
    assert supervisor2.get("/api/audit").status_code == 200


def test_audit_pagination_and_filters(supervisor):
    first = supervisor.get("/api/audit", params={"page_size": 5}).json()
    assert len(first["items"]) == 5 and first["total"] > 5
    second = supervisor.get("/api/audit", params={"page_size": 5, "page": 2}).json()
    assert not {e["id"] for e in first["items"]} & {e["id"] for e in second["items"]}
    work = supervisor.get("/api/audit", params={"category": "work", "app": "refund"}).json()["items"]
    assert work and all(e["category"] == "work" and e["record_type"] == "refund" for e in work)
    system = supervisor.get("/api/audit", params={"actor_id": "system"}).json()["items"]
    assert system and all(e["actor_name"] == "System (automated)" for e in system)


def test_no_update_or_delete_routes_for_activity():
    paths = {p: ops for p, ops in app.openapi()["paths"].items() if p.startswith(("/api/activity", "/api/audit"))}
    assert set(paths) == {"/api/activity", "/api/audit"}
    for path, operations in paths.items():
        assert set(operations) == {"get"}, path


def test_api_cannot_edit_or_delete_entries(supervisor):
    entry = supervisor.get("/api/audit", params={"page_size": 1}).json()["items"][0]
    for path in (f"/api/activity/{entry['id']}", f"/api/audit/{entry['id']}"):
        assert supervisor.put(path, json={"note": "x"}).status_code in (404, 405)
        assert supervisor.patch(path, json={"note": "x"}).status_code in (404, 405)
        assert supervisor.delete(path).status_code in (404, 405)
    assert supervisor.delete("/api/activity").status_code == 405
    assert supervisor.delete("/api/audit").status_code == 405


def test_orm_refuses_update_and_delete():
    with SessionLocal() as db:
        entry = db.scalars(select(Activity).limit(1)).one()
        entry.note = "tampered"
        with pytest.raises(AppendOnlyViolation):
            db.commit()
        db.rollback()
        entry = db.scalars(select(Activity).limit(1)).one()
        db.delete(entry)
        with pytest.raises(AppendOnlyViolation):
            db.commit()


def test_mutation_and_audit_share_transaction_and_request_id(reviewer, supervisor):
    r = reviewer.post("/api/kyc/KYC-1001/decision", json={"action": "approve", "note": "ok"})
    request_id = r.headers["X-Request-ID"]
    entries = supervisor.get("/api/audit", params={"request_id": request_id}).json()["items"]
    assert sorted(e["action"] for e in entries) == ["approve", "task_completed"]
    decision = next(e for e in entries if e["action"] == "approve")
    assert decision["actor_id"] == "reviewer" and decision["previous_status"] == "pending_review"


def test_failed_mutation_writes_no_audit(reviewer, supervisor):
    before = supervisor.get("/api/audit").json()["total"]
    assert reviewer.post("/api/kyc/KYC-1004/decision", json={"action": "reject", "note": "x"}).status_code == 409
    assert reviewer.post("/api/kyc/KYC-1003/decision", json={"action": "reject", "note": " "}).status_code == 422
    assert supervisor.get("/api/audit").json()["total"] == before


def test_sensitive_views_downloads_and_exports_are_logged(viewer, reviewer, supervisor):
    viewer.get("/api/chargebacks/CBK-2001")
    viewer.get("/api/chargebacks/CBK-2001")  # deduplicated within the window
    viewer.get("/api/kyc/KYC-1002")
    upload = reviewer.post(
        "/api/chargebacks/CBK-2001/attachments", params={"filename": "secret.txt"},
        content=b"SENSITIVE-CONTENT-123", headers={"Content-Type": "text/plain"},
    ).json()
    att = upload["attachments"][0]
    assert viewer.get(f"/api/chargebacks/CBK-2001/attachments/{att['id']}").status_code == 200
    assert viewer.get("/api/chargebacks/CBK-2001/summary.pdf").status_code == 200
    access = supervisor.get("/api/audit", params={"category": "access", "actor_id": "viewer"}).json()["items"]
    actions = sorted((e["record_id"], e["action"]) for e in access)
    assert actions == [
        ("CBK-2001", "attachment_downloaded"),
        ("CBK-2001", "record_viewed"),
        ("CBK-2001", "summary_exported"),
        ("KYC-1002", "record_viewed"),
    ]
    everything = supervisor.get("/api/audit", params={"page_size": 100}).json()["items"]
    assert not any("SENSITIVE-CONTENT-123" in str(e) for e in everything)


def test_case_history_defaults_to_case_events(viewer, supervisor):
    viewer.get("/api/kyc/KYC-1001")
    default = viewer.get("/api/activity", params={"record_type": "kyc", "record_id": "KYC-1001"}).json()
    assert default == []
    full = viewer.get(
        "/api/activity",
        params=[("record_type", "kyc"), ("record_id", "KYC-1001"), ("category", "case"),
                ("category", "work"), ("category", "access")],
    ).json()
    assert {e["action"] for e in full} == {"task_created", "task_assigned", "record_viewed"}
