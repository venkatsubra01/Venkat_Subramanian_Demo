import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.refunds import RefundException

EVENT = {
    "event_id": "evt_test_42",
    "payment_reference": "pay_test_42",
    "amount_minor": 2599,
    "currency": "USD",
    "failure_reason": "Card account closed.",
}


def _count(client):
    return sum(client.get("/api/refunds").json()["status_counts"].values())


def _activity(client, record_id):
    return client.get("/api/activity", params={"record_type": "refund", "record_id": record_id}).json()


def test_viewer_cannot_simulate_event(viewer):
    before = _count(viewer)
    assert viewer.post("/api/demo/events/refund-failed", json=EVENT).status_code == 403
    assert _count(viewer) == before


def test_event_creates_exception_with_activity(reviewer):
    response = reviewer.post("/api/demo/events/refund-failed", json=EVENT)
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    record = body["exception"]
    assert record["status"] == "open"
    assert record["amount_minor"] == 2599
    entries = _activity(reviewer, record["id"])
    assert [e["action"] for e in entries] == ["created_from_event"]
    assert entries[0]["new_status"] == "open"


def test_replaying_event_returns_existing_without_duplicate(reviewer):
    first = reviewer.post("/api/demo/events/refund-failed", json=EVENT).json()["exception"]
    count = _count(reviewer)
    replay = reviewer.post("/api/demo/events/refund-failed", json=EVENT)
    assert replay.status_code == 200
    assert replay.json()["created"] is False
    assert replay.json()["exception"]["id"] == first["id"]
    assert _count(reviewer) == count
    assert len(_activity(reviewer, first["id"])) == 1


def test_reused_event_id_with_different_fields_is_409(reviewer):
    reviewer.post("/api/demo/events/refund-failed", json=EVENT)
    count = _count(reviewer)
    response = reviewer.post("/api/demo/events/refund-failed", json={**EVENT, "amount_minor": 9999})
    assert response.status_code == 409
    assert _count(reviewer) == count


def test_event_id_unique_constraint_in_database():
    with SessionLocal() as db:
        db.add(
            RefundException(
                id="RFX-DUP", external_event_id="evt_demo_0001", payment_reference="x",
                amount_minor=1, currency="USD", failure_reason="x", status="open",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "override",
    [{"currency": "usd"}, {"amount_minor": 0}, {"event_id": ""}, {"failure_reason": ""}, {"amount_minor": 1.5}],
)
def test_invalid_event_payload_is_422(reviewer, override):
    assert reviewer.post("/api/demo/events/refund-failed", json={**EVENT, **override}).status_code == 422


def test_decisions_require_note(reviewer):
    for note in (None, "", "   "):
        payload = {"action": "escalate"} if note is None else {"action": "escalate", "note": note}
        assert reviewer.post("/api/refunds/RFX-SEED0001/decision", json=payload).status_code == 422
    assert reviewer.get("/api/refunds/RFX-SEED0001").json()["status"] == "open"


def test_viewer_cannot_decide(viewer):
    response = viewer.post("/api/refunds/RFX-SEED0001/decision", json={"action": "resolve", "note": "x"})
    assert response.status_code == 403
    assert viewer.get("/api/refunds/RFX-SEED0001").json()["status"] == "open"
    assert _activity(viewer, "RFX-SEED0001") == []


def test_escalate_then_resolve_writes_simulated_notification(reviewer):
    r = reviewer.post("/api/refunds/RFX-SEED0001/decision", json={"action": "escalate", "note": "Needs finance"})
    assert r.status_code == 200 and r.json()["status"] == "escalated"
    assert r.json()["allowed_actions"] == ["resolve"]
    r = reviewer.post("/api/refunds/RFX-SEED0001/decision", json={"action": "resolve", "note": "Customer refunded manually"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    actions = [e["action"] for e in _activity(reviewer, "RFX-SEED0001")]
    assert actions == ["notification_simulated", "resolve", "escalate"]


def test_resolved_is_terminal(reviewer):
    r = reviewer.post("/api/refunds/RFX-SEED0003/decision", json={"action": "escalate", "note": "again"})
    assert r.status_code == 409
    r = reviewer.post("/api/refunds/RFX-SEED0002/decision", json={"action": "escalate", "note": "again"})
    assert r.status_code == 409


def test_list_status_filter_and_404(viewer):
    items = viewer.get("/api/refunds", params={"status": "escalated"}).json()["items"]
    assert [i["id"] for i in items] == ["RFX-SEED0002"]
    assert viewer.get("/api/refunds", params={"status": "bogus"}).status_code == 422
    assert viewer.get("/api/refunds/RFX-NOPE").status_code == 404
