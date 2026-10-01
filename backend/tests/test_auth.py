def test_missing_session_is_401(anon):
    assert anon.get("/api/kyc").status_code == 401
    assert anon.post("/api/kyc/KYC-1001/decision", json={"action": "approve"}).status_code == 401


def test_tampered_cookie_is_401(anon):
    anon.cookies.set("demo_session", "reviewer.forged-signature")
    assert anon.get("/api/kyc").status_code == 401


def test_session_reports_server_side_identity(viewer, reviewer):
    assert viewer.get("/api/demo/session").json()["role"] == "viewer"
    assert reviewer.get("/api/demo/session").json()["role"] == "reviewer"


def test_role_in_body_is_ignored(viewer):
    response = viewer.post(
        "/api/kyc/KYC-1001/decision",
        json={"action": "approve", "role": "reviewer", "identity": "reviewer"},
    )
    assert response.status_code == 403


def test_cross_origin_mutation_rejected(reviewer):
    response = reviewer.post(
        "/api/kyc/KYC-1001/decision",
        json={"action": "approve"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert reviewer.get("/api/kyc/KYC-1001").json()["status"] == "pending_review"


def test_same_origin_mutation_allowed(reviewer):
    response = reviewer.post(
        "/api/kyc/KYC-1001/decision",
        json={"action": "approve"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 200
