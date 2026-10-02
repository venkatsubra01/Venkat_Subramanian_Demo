from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.kyc import KycCase, sync_case_task
from app.tasks import WorkTask
from sqlalchemy import func, select


def _all_tasks(client, **params):
    response = client.get("/api/work/tasks", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _task(client, app, record_id):
    return client.get(f"/api/work/by-source/{app}/{record_id}").json()


def _work_activity(client, app, record_id):
    return client.get(
        "/api/activity", params={"record_type": app, "record_id": record_id, "category": "work"}
    ).json()


def test_seed_creates_one_active_task_per_actionable_case(supervisor):
    tasks = _all_tasks(supervisor, state="all")
    keys = [(t["source_app"], t["source_id"]) for t in tasks]
    assert len(keys) == len(set(keys))
    active = {(t["source_app"], t["source_id"]) for t in tasks if t["state"] == "active"}
    # 8 actionable KYC, 2 actionable refunds, 5 non-closed chargebacks
    assert len(active) == 15
    assert ("kyc", "KYC-1004") not in active  # approved
    assert ("refund", "RFX-SEED0003") not in active  # resolved
    assert ("chargeback", "CBK-2006") not in active  # closed


def test_repeated_sync_creates_no_duplicates(supervisor):
    before = len(_all_tasks(supervisor, state="all"))
    for _ in range(3):
        result = supervisor.post("/api/work/sync").json()
        assert result == {"created": 0, "completed": 0, "reactivated": 0}
    assert len(_all_tasks(supervisor, state="all")) == before
    with SessionLocal() as db:
        dupes = db.execute(
            select(WorkTask.source_app, WorkTask.source_id, func.count())
            .group_by(WorkTask.source_app, WorkTask.source_id)
            .having(func.count() > 1)
        ).all()
    assert dupes == []


def test_database_rejects_duplicate_task():
    with SessionLocal() as db:
        db.add(WorkTask(source_app="kyc", source_id="KYC-1001", kind="review", state="active", priority="normal"))
        try:
            db.commit()
            raised = False
        except Exception:
            db.rollback()
            raised = True
    assert raised


def test_work_list_and_management_are_supervisor_only(viewer, reviewer, supervisor):
    task = _task(supervisor, "chargeback", "CBK-2003")
    for client in (viewer, reviewer):
        assert client.get("/api/work/tasks").status_code == 403
        assert client.patch(f"/api/work/tasks/{task['id']}", json={"assignee_id": "reviewer"}).status_code == 403
        assert client.post("/api/work/sync").status_code == 403
    assert _task(supervisor, "chargeback", "CBK-2003")["assignee_id"] is None


def test_assignment_appears_in_my_work_and_reassignment_moves_it(supervisor, reviewer, reviewer2):
    task = _task(supervisor, "chargeback", "CBK-2003")
    assert task["id"] not in [t["id"] for t in reviewer.get("/api/work/mine").json()["items"]]

    r = supervisor.patch(f"/api/work/tasks/{task['id']}", json={"assignee_id": "reviewer", "reason": "Has context"})
    assert r.status_code == 200 and r.json()["assignee_name"] == "Riley Reviewer"
    mine = reviewer.get("/api/work/mine").json()["items"]
    assert task["id"] in [t["id"] for t in mine]
    assert next(t for t in mine if t["id"] == task["id"])["source_app"] == "chargeback"

    supervisor.patch(f"/api/work/tasks/{task['id']}", json={"assignee_id": "reviewer2"})
    assert task["id"] not in [t["id"] for t in reviewer.get("/api/work/mine").json()["items"]]
    assert task["id"] in [t["id"] for t in reviewer2.get("/api/work/mine").json()["items"]]

    actions = [(e["action"], e["actor_id"], e["before_values"], e["after_values"], e["task_id"])
               for e in reversed(_work_activity(supervisor, "chargeback", "CBK-2003"))]
    assert actions[-2:] == [
        ("task_assigned", "supervisor", {"assignee_id": None}, {"assignee_id": "reviewer"}, task["id"]),
        ("task_reassigned", "supervisor", {"assignee_id": "reviewer"}, {"assignee_id": "reviewer2"}, task["id"]),
    ]


def test_only_eligible_employees_can_be_assigned(supervisor):
    task = _task(supervisor, "kyc", "KYC-1003")
    for bad in ("viewer", "supervisor2", "system", "nobody"):
        r = supervisor.patch(f"/api/work/tasks/{task['id']}", json={"assignee_id": bad})
        assert r.status_code == 422, bad
    assert _task(supervisor, "kyc", "KYC-1003")["assignee_id"] is None
    assert {a["id"] for a in supervisor.get("/api/work/assignees").json()} == {"reviewer", "reviewer2", "supervisor"}


def test_assignment_does_not_grant_case_access(supervisor, supervisor2):
    task = _task(supervisor, "kyc", "KYC-1003")
    # Pat (supervisor only) is not eligible, and still cannot act on cases.
    assert supervisor.patch(f"/api/work/tasks/{task['id']}", json={"assignee_id": "supervisor2"}).status_code == 422
    r = supervisor2.post("/api/kyc/KYC-1003/decision", json={"action": "approve"})
    assert r.status_code == 403


def test_deadline_priority_and_overdue_filters(supervisor):
    task = _task(supervisor, "kyc", "KYC-1009")
    assert task["due_at"] is None and not task["is_overdue"]
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    r = supervisor.patch(f"/api/work/tasks/{task['id']}", json={"due_at": past, "priority": "high"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_overdue"] and body["priority"] == "high" and body["due_at"].endswith("Z")
    assert task["id"] in [t["id"] for t in _all_tasks(supervisor, overdue="true")]
    assert task["id"] in [t["id"] for t in _all_tasks(supervisor, priority="high", app="kyc")]

    # A deadline given with an offset is stored as the same instant in UTC.
    future = datetime(2030, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    r = supervisor.patch(f"/api/work/tasks/{task['id']}", json={"due_at": future.isoformat()})
    assert r.json()["due_at"] == "2030-01-01T17:00:00Z" and not r.json()["is_overdue"]
    assert task["id"] not in [t["id"] for t in _all_tasks(supervisor, overdue="true")]

    r = supervisor.patch(f"/api/work/tasks/{task['id']}", json={"due_at": None})
    assert r.json()["due_at"] is None
    actions = [e["action"] for e in reversed(_work_activity(supervisor, "kyc", "KYC-1009"))]
    assert actions.count("task_deadline_changed") == 3 and actions.count("task_priority_changed") == 1


def test_unassigned_and_assignee_filters(supervisor):
    unassigned = _all_tasks(supervisor, unassigned="true")
    assert unassigned and all(t["assignee_id"] is None for t in unassigned)
    riley = _all_tasks(supervisor, assignee_id="reviewer")
    assert {t["source_id"] for t in riley} == {"KYC-1001", "CBK-2001"}


def test_completed_case_completes_task_and_task_cannot_be_managed(reviewer, supervisor):
    task = _task(supervisor, "kyc", "KYC-1001")
    assert task["state"] == "active"
    assert reviewer.post("/api/kyc/KYC-1001/decision", json={"action": "approve"}).status_code == 200
    task = _task(supervisor, "kyc", "KYC-1001")
    assert task["state"] == "completed" and task["completed_at"]
    assert task["id"] not in [t["id"] for t in reviewer.get("/api/work/mine").json()["items"]]
    assert supervisor.patch(f"/api/work/tasks/{task['id']}", json={"priority": "low"}).status_code == 409
    entry = _work_activity(supervisor, "kyc", "KYC-1001")[0]
    assert entry["action"] == "task_completed" and entry["actor_id"] == "system"


def test_no_generic_complete_endpoint(supervisor):
    task = _task(supervisor, "kyc", "KYC-1003")
    assert supervisor.post(f"/api/work/tasks/{task['id']}/complete").status_code in (404, 405)
    r = supervisor.patch(f"/api/work/tasks/{task['id']}", json={"state": "completed"})
    assert r.status_code == 422
    assert _task(supervisor, "kyc", "KYC-1003")["state"] == "active"


def test_refund_task_follows_source_and_new_events_get_one_task(reviewer, supervisor):
    payload = {"event_id": "evt_task_1", "payment_reference": "pay_x", "amount_minor": 100,
               "currency": "USD", "failure_reason": "Card closed"}
    created = reviewer.post("/api/demo/events/refund-failed", json=payload).json()["exception"]
    reviewer.post("/api/demo/events/refund-failed", json=payload)  # replay
    tasks = [t for t in _all_tasks(supervisor, app="refund", state="all") if t["source_id"] == created["id"]]
    assert len(tasks) == 1 and tasks[0]["state"] == "active"
    reviewer.post(f"/api/refunds/{created['id']}/decision", json={"action": "resolve", "note": "done"})
    assert _task(supervisor, "refund", created["id"])["state"] == "completed"


def test_kyc_return_to_review_keeps_task_active(reviewer, supervisor):
    reviewer.post("/api/kyc/KYC-1003/decision", json={"action": "request_information", "note": "need doc"})
    assert _task(supervisor, "kyc", "KYC-1003")["state"] == "active"
    reviewer.post("/api/kyc/KYC-1003/decision", json={"action": "return_to_review", "note": "got it"})
    assert _task(supervisor, "kyc", "KYC-1003")["state"] == "active"


def test_reopened_case_reactivates_its_task(supervisor):
    """No current workflow reopens a terminal case; the sync helper still handles it if one does."""
    supervisor.post("/api/kyc/KYC-1003/decision", json={"action": "approve"})
    task = _task(supervisor, "kyc", "KYC-1003")
    assert task["state"] == "completed"
    with SessionLocal() as db:
        case = db.get(KycCase, "KYC-1003")
        case.status = "pending_review"
        sync_case_task(db, case)
        db.commit()
    again = _task(supervisor, "kyc", "KYC-1003")
    assert again["id"] == task["id"] and again["state"] == "active" and again["completed_at"] is None
