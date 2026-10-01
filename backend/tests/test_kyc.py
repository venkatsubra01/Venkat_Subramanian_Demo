def _activity(client, case_id):
    return client.get("/api/activity", params={"record_type": "kyc", "record_id": case_id}).json()


def test_list_search_and_status_filter(viewer):
    body = viewer.get("/api/kyc", params={"search": "ada"}).json()
    assert [c["id"] for c in body["items"]] == ["KYC-1001"]
    body = viewer.get("/api/kyc", params={"status": "approved"}).json()
    assert {c["status"] for c in body["items"]} == {"approved"}
    assert body["status_counts"]["pending_review"] == 6


def test_invalid_list_params_are_422(viewer):
    assert viewer.get("/api/kyc", params={"status": "bogus"}).status_code == 422
    assert viewer.get("/api/kyc", params={"limit": 1000}).status_code == 422


def test_missing_case_is_404(viewer):
    assert viewer.get("/api/kyc/KYC-9999").status_code == 404


def test_viewer_cannot_decide_and_data_unchanged(viewer):
    response = viewer.post("/api/kyc/KYC-1001/decision", json={"action": "approve", "note": "ok"})
    assert response.status_code == 403
    assert viewer.get("/api/kyc/KYC-1001").json()["status"] == "pending_review"
    assert _activity(viewer, "KYC-1001") == []


def test_valid_decision_changes_status_and_writes_activity(reviewer):
    response = reviewer.post(
        "/api/kyc/KYC-1002/decision", json={"action": "reject", "note": "  Watchlist match confirmed.  "}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["allowed_actions"] == []
    entries = _activity(reviewer, "KYC-1002")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["actor_id"] == "reviewer"
    assert entry["action"] == "reject"
    assert entry["previous_status"] == "pending_review"
    assert entry["new_status"] == "rejected"
    assert entry["note"] == "Watchlist match confirmed."
    assert entry["created_at"].endswith("Z")


def test_approve_note_optional(reviewer):
    response = reviewer.post("/api/kyc/KYC-1001/decision", json={"action": "approve"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_invalid_transition_is_409_and_no_activity(reviewer):
    response = reviewer.post("/api/kyc/KYC-1004/decision", json={"action": "reject", "note": "late"})
    assert response.status_code == 409
    assert reviewer.get("/api/kyc/KYC-1004").json()["status"] == "approved"
    assert _activity(reviewer, "KYC-1004") == []


def test_required_note_enforced(reviewer):
    for action in ("reject", "request_information"):
        response = reviewer.post("/api/kyc/KYC-1003/decision", json={"action": action, "note": "   "})
        assert response.status_code == 422
    response = reviewer.post("/api/kyc/KYC-1005/decision", json={"action": "return_to_review"})
    assert response.status_code == 422
    assert reviewer.get("/api/kyc/KYC-1003").json()["status"] == "pending_review"


def test_request_info_then_return_to_review(reviewer):
    r = reviewer.post("/api/kyc/KYC-1007/decision", json={"action": "request_information", "note": "Send DOB proof"})
    assert r.json()["status"] == "awaiting_information"
    assert r.json()["allowed_actions"] == ["return_to_review"]
    r = reviewer.post("/api/kyc/KYC-1007/decision", json={"action": "return_to_review", "note": "Received"})
    assert r.json()["status"] == "pending_review"
    assert [e["action"] for e in _activity(reviewer, "KYC-1007")] == ["return_to_review", "request_information"]


def test_unknown_action_is_422(reviewer):
    assert reviewer.post("/api/kyc/KYC-1001/decision", json={"action": "delete"}).status_code == 422
