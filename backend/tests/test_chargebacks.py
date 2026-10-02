import pytest

from app.chargebacks import MAX_ATTACHMENT_BYTES, attachment_path
from app.db import SessionLocal
from app.main import app  # noqa: F401  (registers routes)
from app.refunds import RefundException

PDF_BYTES = b"%PDF-1.4\n% fictional evidence\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _detail(client, case_id):
    response = client.get(f"/api/chargebacks/{case_id}")
    assert response.status_code == 200
    return response.json()


def _activity(client, case_id):
    """Oldest first (the API returns newest first)."""
    entries = client.get("/api/activity", params={"record_type": "chargeback", "record_id": case_id}).json()
    return list(reversed(entries))


def _upload(client, case_id, data=PDF_BYTES, filename="receipt.pdf", content_type="application/pdf"):
    return client.post(
        f"/api/chargebacks/{case_id}/attachments",
        params={"filename": filename},
        content=data,
        headers={"Content-Type": content_type},
    )


# ---------------------------------------------------------------- reads and links


def test_list_requires_session(anon):
    assert anon.get("/api/chargebacks").status_code == 401
    assert anon.get("/api/chargebacks/CBK-2001").status_code == 401
    assert anon.get("/api/chargebacks/CBK-2001/summary.pdf").status_code == 401


def test_list_columns_filter_and_overdue(viewer):
    body = viewer.get("/api/chargebacks").json()
    assert len(body["items"]) == 6
    first = body["items"][0]
    for field in ("cardholder_name", "payment_reference", "amount_minor", "currency", "reason", "evidence_due_at", "status"):
        assert field in first
    overdue = {i["id"] for i in body["items"] if i["is_overdue"]}
    # CBK-2006 is past its deadline but closed, so it is not overdue.
    assert overdue == {"CBK-2001", "CBK-2005"}
    assert body["overdue_count"] == 2
    assert body["status_counts"] == {"open": 2, "collecting_evidence": 2, "ready_for_review": 1, "closed": 1}

    collecting = viewer.get("/api/chargebacks", params={"status": "collecting_evidence"}).json()["items"]
    assert {i["id"] for i in collecting} == {"CBK-2001", "CBK-2004"}
    only_overdue = viewer.get("/api/chargebacks", params={"overdue": "true"}).json()["items"]
    assert {i["id"] for i in only_overdue} == {"CBK-2001", "CBK-2005"}
    assert viewer.get("/api/chargebacks", params={"status": "won"}).status_code == 422


def test_detail_links_payment_customer_and_refund_history(viewer):
    detail = _detail(viewer, "CBK-2001")
    assert detail["payment"]["reference"] == "pay_demo_A1001"
    assert detail["customer"]["kyc_case_id"] == "KYC-1004"
    assert [r["id"] for r in detail["refunds"]] == ["RFX-SEED0001"]
    assert detail["allowed_actions"] == ["mark_ready"]
    assert not any("payment" in m.lower() for m in detail["missing_information"])


def test_refund_created_later_appears_in_linked_history(reviewer):
    event = {
        "event_id": "evt_cbk_link",
        "payment_reference": "pay_demo_D4004",
        "amount_minor": 8900,
        "currency": "USD",
        "failure_reason": "Card expired.",
    }
    created = reviewer.post("/api/demo/events/refund-failed", json=event).json()["exception"]
    assert [r["id"] for r in _detail(reviewer, "CBK-2004")["refunds"]] == [created["id"]]


def test_missing_links_are_reported(viewer):
    unlinked = _detail(viewer, "CBK-2005")
    assert unlinked["payment"]["reference"] == "pay_demo_E5005"
    assert unlinked["customer"] is None
    assert "Payment is not linked to a KYC customer." in unlinked["missing_information"]

    missing = _detail(viewer, "CBK-2006")
    assert missing["payment"] is None and missing["customer"] is None and missing["refunds"] == []
    assert "No payment record found for reference pay_demo_F6006." in missing["missing_information"]


def test_unknown_case_404(viewer):
    assert viewer.get("/api/chargebacks/CBK-9999").status_code == 404


# ---------------------------------------------------------------- permissions


def test_viewer_cannot_mutate_anything(viewer, reviewer):
    upload = _upload(reviewer, "CBK-2001")
    attachment_id = upload.json()["attachments"][0]["id"]
    before = _detail(viewer, "CBK-2001")
    activity_before = _activity(viewer, "CBK-2001")

    assert viewer.post("/api/chargebacks/CBK-2001/decision", json={"action": "mark_ready"}).status_code == 403
    assert viewer.put("/api/chargebacks/CBK-2001/checklist/refund_policy", json={"done": True}).status_code == 403
    assert viewer.put("/api/chargebacks/CBK-2001/notes", json={"notes": "viewer edit"}).status_code == 403
    assert _upload(viewer, "CBK-2001").status_code == 403
    # Role in the body is ignored.
    assert viewer.post(
        "/api/chargebacks/CBK-2001/decision", json={"action": "mark_ready", "role": "reviewer"}
    ).status_code == 403

    assert _detail(viewer, "CBK-2001") == before
    assert _activity(viewer, "CBK-2001") == activity_before
    # Viewer can still read and download.
    assert viewer.get(f"/api/chargebacks/CBK-2001/attachments/{attachment_id}").status_code == 200


def test_cross_origin_mutation_rejected(reviewer):
    response = reviewer.put(
        "/api/chargebacks/CBK-2001/notes", json={"notes": "x"}, headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert _detail(reviewer, "CBK-2001")["notes"] == ""


# ---------------------------------------------------------------- workflow


def test_full_workflow_with_activity(reviewer):
    path = "/api/chargebacks/CBK-2002/decision"
    assert reviewer.post(path, json={"action": "start_collecting"}).json()["status"] == "collecting_evidence"
    assert reviewer.post(path, json={"action": "mark_ready", "note": "All evidence in."}).json()["status"] == "ready_for_review"
    closed = reviewer.post(path, json={"action": "close", "outcome": "won", "note": "Issuer reversed."}).json()
    assert closed["status"] == "closed" and closed["outcome"] == "won" and closed["closed_at"]
    assert closed["allowed_actions"] == []

    entries = _activity(reviewer, "CBK-2002")
    assert [(e["action"], e["previous_status"], e["new_status"]) for e in entries] == [
        ("start_collecting", "open", "collecting_evidence"),
        ("mark_ready", "collecting_evidence", "ready_for_review"),
        ("close", "ready_for_review", "closed"),
    ]
    assert entries[2]["note"] == "Outcome: won. Issuer reversed."
    assert all(e["actor_id"] == "reviewer" for e in entries)


@pytest.mark.parametrize(
    "case_id,action",
    [("CBK-2002", "mark_ready"), ("CBK-2002", "close"), ("CBK-2001", "start_collecting"), ("CBK-2006", "start_collecting")],
)
def test_invalid_transitions_409(reviewer, case_id, action):
    body = {"action": action, "outcome": "lost"} if action == "close" else {"action": action}
    before = _detail(reviewer, case_id)["status"]
    assert reviewer.post(f"/api/chargebacks/{case_id}/decision", json=body).status_code == 409
    assert _detail(reviewer, case_id)["status"] == before
    assert _activity(reviewer, case_id) == []


def test_close_requires_outcome(reviewer):
    path = "/api/chargebacks/CBK-2003/decision"
    assert reviewer.post(path, json={"action": "close"}).status_code == 422
    assert reviewer.post(path, json={"action": "close", "outcome": "maybe"}).status_code == 422
    assert reviewer.post(path, json={"action": "start_collecting", "outcome": "won"}).status_code == 422
    assert _detail(reviewer, "CBK-2003")["status"] == "ready_for_review"
    assert _activity(reviewer, "CBK-2003") == []


# ---------------------------------------------------------------- checklist and notes


def test_checklist_and_notes_persist_with_activity(reviewer, viewer):
    detail = reviewer.put("/api/chargebacks/CBK-2001/checklist/refund_policy", json={"done": True}).json()
    item = next(i for i in detail["checklist"] if i["item_key"] == "refund_policy")
    assert item["done"] is True and item["updated_by"] == "Riley Reviewer"
    # Repeating the same value is a no-op and writes no activity.
    reviewer.put("/api/chargebacks/CBK-2001/checklist/refund_policy", json={"done": True})
    reviewer.put("/api/chargebacks/CBK-2001/checklist/receipt", json={"done": False})
    reviewer.put("/api/chargebacks/CBK-2001/notes", json={"notes": "  Customer confirmed refund policy.  "})

    # A fresh client (viewer) sees the persisted state.
    persisted = _detail(viewer, "CBK-2001")
    assert persisted["notes"] == "Customer confirmed refund policy."
    assert persisted["notes_updated_by"] == "Riley Reviewer"
    done = {i["item_key"]: i["done"] for i in persisted["checklist"]}
    assert done["refund_policy"] is True and done["receipt"] is False
    assert [(e["action"], e["note"]) for e in _activity(viewer, "CBK-2001")] == [
        ("checklist_completed", "Refund policy shown to the customer"),
        ("checklist_reopened", "Receipt or invoice for the payment"),
        ("notes_updated", "Customer confirmed refund policy."),
    ]


def test_checklist_unknown_item_404_and_closed_case_read_only(reviewer):
    assert reviewer.put("/api/chargebacks/CBK-2001/checklist/nope", json={"done": True}).status_code == 404
    assert reviewer.put("/api/chargebacks/CBK-2006/checklist/receipt", json={"done": True}).status_code == 409
    assert reviewer.put("/api/chargebacks/CBK-2006/notes", json={"notes": "late"}).status_code == 409
    assert _upload(reviewer, "CBK-2006").status_code == 409


def test_notes_length_limit(reviewer):
    assert reviewer.put("/api/chargebacks/CBK-2001/notes", json={"notes": "x" * 5001}).status_code == 422


# ---------------------------------------------------------------- attachments


def test_upload_and_download_round_trip(reviewer, viewer, anon):
    response = _upload(reviewer, "CBK-2001", filename="../../etc/passwd receipt.pdf")
    assert response.status_code == 201
    attachment = response.json()["attachments"][0]
    assert attachment["filename"] == "passwd receipt.pdf"
    assert attachment["size_bytes"] == len(PDF_BYTES)
    assert attachment_path("CBK-2001", attachment["id"]).read_bytes() == PDF_BYTES

    url = f"/api/chargebacks/CBK-2001/attachments/{attachment['id']}"
    download = viewer.get(url)
    assert download.status_code == 200
    assert download.content == PDF_BYTES
    assert download.headers["content-type"] == "application/pdf"
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"
    assert anon.get(url).status_code == 401
    # Attachment ids are scoped to their case.
    assert viewer.get(f"/api/chargebacks/CBK-2002/attachments/{attachment['id']}").status_code == 404

    entries = _activity(viewer, "CBK-2001")
    assert entries[-1]["action"] == "attachment_uploaded"
    assert "passwd receipt.pdf" in entries[-1]["note"]


def test_png_upload_accepted(reviewer):
    assert _upload(reviewer, "CBK-2004", PNG_BYTES, "tracking.png", "image/png").status_code == 201


@pytest.mark.parametrize(
    "data,filename,content_type,status",
    [
        (b"MZ\x90\x00", "tool.exe", "application/octet-stream", 415),
        (b"<script>", "page.html", "text/html", 415),
        (PDF_BYTES, "receipt.png", "application/pdf", 415),  # extension mismatch
        (b"not a pdf", "receipt.pdf", "application/pdf", 415),  # content sniff
        (b"\x00\x01binary", "notes.txt", "text/plain", 415),
        (b"", "empty.txt", "text/plain", 422),
        (b"%PDF-" + b"0" * MAX_ATTACHMENT_BYTES, "big.pdf", "application/pdf", 413),
    ],
)
def test_upload_restrictions(reviewer, data, filename, content_type, status):
    assert _upload(reviewer, "CBK-2001", data, filename, content_type).status_code == status
    assert _detail(reviewer, "CBK-2001")["attachments"] == []


def test_upload_to_unknown_case_404(reviewer):
    assert _upload(reviewer, "CBK-9999").status_code == 404


# ---------------------------------------------------------------- PDF summary


def test_pdf_summary_contents(reviewer, viewer):
    reviewer.put("/api/chargebacks/CBK-2001/notes", json={"notes": "Refund policy (v2) was shown at checkout."})
    _upload(reviewer, "CBK-2001", b"Fictional email thread", "customer-email.txt", "text/plain")
    with SessionLocal() as db:
        assert db.get(RefundException, "RFX-SEED0001") is not None

    response = viewer.get("/api/chargebacks/CBK-2001/summary.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="CBK-2001-evidence-summary.pdf"' in response.headers["content-disposition"]
    pdf = response.content
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    for expected in [
        b"Chargeback evidence summary",
        b"NOT A SUBMISSION PACKAGE",
        b"Case details",
        b"pay_demo_A1001",
        b"KYC-1004",
        b"Transaction and refund history",
        b"RFX-SEED0001",
        b"Destination card account closed.",
        b"Evidence checklist",
        b"Refund policy \\(v2\\) was shown at checkout.",
        b"Attachment inventory",
        b"customer-email.txt",
        b"attachment_uploaded by Riley Reviewer",
    ]:
        assert expected in pdf, expected


def test_pdf_reports_missing_information(viewer):
    pdf = viewer.get("/api/chargebacks/CBK-2006/summary.pdf").content
    assert b"No payment record found for reference pay_demo_F6006." in pdf
    assert b"No refund exceptions recorded for this payment." in pdf
    assert b"outcome: lost" in pdf
