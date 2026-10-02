"""Chargeback evidence approval: CBK-2003 is seeded as ready_for_review."""

CASE = "CBK-2003"


def _detail(client, case_id=CASE):
    return client.get(f"/api/chargebacks/{case_id}").json()


def _request(client, case_id=CASE):
    return client.post(f"/api/chargebacks/{case_id}/approval-requests")


def _approve(client, approval_id, version, case_id=CASE):
    return client.post(
        f"/api/chargebacks/{case_id}/approval-requests/{approval_id}/approve", json={"evidence_version": version}
    )


def _return(client, approval_id, version, reason, case_id=CASE):
    return client.post(
        f"/api/chargebacks/{case_id}/approval-requests/{approval_id}/return",
        json={"evidence_version": version, "reason": reason},
    )


def _task(client, case_id=CASE):
    return client.get(f"/api/work/by-source/chargeback/{case_id}").json()


def test_request_and_approve_by_different_supervisor(reviewer, supervisor2):
    r = _request(reviewer)
    assert r.status_code == 201, r.text
    body = r.json()
    approval = body["approvals"][0]
    assert approval["state"] == "pending" and approval["evidence_version"] == body["evidence_version"]
    assert approval["requested_by_id"] == "reviewer" and not body["can_request_approval"]
    snapshot = approval["snapshot"]
    assert snapshot["evidence_version"] == body["evidence_version"]
    assert {i["item_key"] for i in snapshot["checklist"] if i["done"]} == {"receipt", "distinct_charges", "refund_records"}

    inbox = supervisor2.get("/api/approvals").json()
    assert [i["id"] for i in inbox["items"]] == [approval["id"]]
    assert inbox["items"][0]["source_status"] == "ready_for_review"

    r = _approve(supervisor2, approval["id"], approval["evidence_version"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready_for_submission"
    assert body["approvals"][0]["state"] == "approved" and body["approvals"][0]["decided_by_id"] == "supervisor2"
    assert supervisor2.get("/api/approvals").json()["items"] == []
    # Awaiting submission is not terminal: the task stays active until the case is closed.
    assert _task(supervisor2)["state"] == "active"


def test_task_stays_active_until_case_closed(reviewer, supervisor2):
    approval = _request(reviewer).json()["approvals"][0]
    assert _task(reviewer)["state"] == "active"
    _approve(supervisor2, approval["id"], approval["evidence_version"])
    r = reviewer.post(f"/api/chargebacks/{CASE}/decision", json={"action": "close", "outcome": "won"})
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert _task(reviewer)["state"] == "completed"


def test_self_approval_refused_even_for_supervisor(supervisor, supervisor2):
    approval = _request(supervisor).json()["approvals"][0]  # Sky can act on cases and supervise
    r = _approve(supervisor, approval["id"], approval["evidence_version"])
    assert r.status_code == 403
    r = _return(supervisor, approval["id"], approval["evidence_version"], "self-return")
    assert r.status_code == 403
    assert _detail(supervisor)["status"] == "ready_for_review"
    assert _approve(supervisor2, approval["id"], approval["evidence_version"]).status_code == 200


def test_only_supervisors_decide_and_only_case_actors_request(viewer, reviewer, reviewer2, supervisor2):
    assert _request(viewer).status_code == 403
    assert _request(supervisor2).status_code == 403  # supervisor-only identity has no case permission
    approval = _request(reviewer).json()["approvals"][0]
    for client in (viewer, reviewer2):
        assert _approve(client, approval["id"], approval["evidence_version"]).status_code == 403
        assert client.get("/api/approvals").status_code == 403
    assert _detail(reviewer)["approvals"][0]["state"] == "pending"


def test_request_requires_ready_for_review_and_no_duplicate_pending(reviewer):
    assert _request(reviewer, "CBK-2002").status_code == 409  # open
    assert _request(reviewer).status_code == 201
    assert _request(reviewer).status_code == 409


def test_return_requires_explanation(reviewer, supervisor2):
    approval = _request(reviewer).json()["approvals"][0]
    for reason in ("", "   "):
        assert _return(supervisor2, approval["id"], approval["evidence_version"], reason).status_code == 422
    r = _return(supervisor2, approval["id"], approval["evidence_version"], "Need proof of second purchase")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready_for_review" and body["approvals"][0]["state"] == "returned"
    assert body["approvals"][0]["decision_reason"] == "Need proof of second purchase"
    assert body["can_request_approval"]


def test_evidence_change_invalidates_pending_and_stale_approve_fails(reviewer, supervisor2):
    approval = _request(reviewer).json()["approvals"][0]
    version = approval["evidence_version"]
    r = reviewer.put(f"/api/chargebacks/{CASE}/notes", json={"notes": "Added merchant statement."})
    assert r.json()["evidence_version"] == version + 1
    assert r.json()["approvals"][0]["state"] == "invalidated"
    r = _approve(supervisor2, approval["id"], version)
    assert r.status_code == 409
    assert _detail(reviewer)["status"] == "ready_for_review"


def test_approving_with_an_outdated_reviewed_version_fails(reviewer, supervisor2):
    approval = _request(reviewer).json()["approvals"][0]
    r = _approve(supervisor2, approval["id"], approval["evidence_version"] - 1 or 99)
    assert r.status_code == 409 and "Stale" in r.json()["detail"]
    assert _detail(reviewer)["approvals"][0]["state"] == "pending"


def test_evidence_change_after_approval_withdraws_ready_for_submission(reviewer, supervisor2):
    approval = _request(reviewer).json()["approvals"][0]
    _approve(supervisor2, approval["id"], approval["evidence_version"])
    r = reviewer.put(f"/api/chargebacks/{CASE}/checklist/receipt", json={"done": False})
    body = r.json()
    assert body["status"] == "ready_for_review"
    assert body["approvals"][0]["state"] == "invalidated"
    assert body["approvals"][0]["invalidated_reason"].startswith("Evidence changed (checklist: receipt)")
    # Upload also counts as an evidence change.
    approval2 = _request(reviewer).json()["approvals"][0]
    assert approval2["evidence_version"] == body["evidence_version"]
    r = reviewer.post(
        f"/api/chargebacks/{CASE}/attachments", params={"filename": "extra.txt"},
        content=b"more evidence", headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 201 and r.json()["approvals"][0]["state"] == "invalidated"
    entries = reviewer.get("/api/activity", params={"record_type": "chargeback", "record_id": CASE}).json()
    withdrawn = next(e for e in entries if e["action"] == "approval_withdrawn")
    assert withdrawn["actor_id"] == "system" and withdrawn["new_status"] == "ready_for_review"


def test_ready_for_submission_only_via_approval(reviewer):
    for action in ("mark_ready_for_submission", "submit"):
        r = reviewer.post(f"/api/chargebacks/{CASE}/decision", json={"action": action})
        assert r.status_code == 422
    assert _detail(reviewer)["status"] == "ready_for_review"


def test_closing_invalidates_pending_request(reviewer, supervisor2):
    approval = _request(reviewer).json()["approvals"][0]
    reviewer.post(f"/api/chargebacks/{CASE}/decision", json={"action": "close", "outcome": "accepted"})
    assert _detail(reviewer)["approvals"][0]["state"] == "invalidated"
    assert _approve(supervisor2, approval["id"], approval["evidence_version"]).status_code == 409


def test_approval_audit_entries_link_request(reviewer, supervisor2):
    approval = _request(reviewer).json()["approvals"][0]
    _approve(supervisor2, approval["id"], approval["evidence_version"])
    page = supervisor2.get("/api/audit", params={"approval_id": approval["id"]}).json()
    actions = sorted(e["action"] for e in page["items"])
    assert actions == ["approval_approved", "approval_requested", "mark_ready_for_submission"]
    approved = next(e for e in page["items"] if e["action"] == "approval_approved")
    status_change = next(e for e in page["items"] if e["action"] == "mark_ready_for_submission")
    assert approved["request_id"] == status_change["request_id"]
    assert approved["after_values"] == {"state": "approved", "evidence_version": approval["evidence_version"]}
