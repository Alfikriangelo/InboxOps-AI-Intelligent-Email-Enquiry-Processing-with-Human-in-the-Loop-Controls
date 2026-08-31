from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def _create_pending_enquiry(message="Pricing request for 10 seats, budget 10k"):
    payload = {
        "source": "email",
        "sender_name": "Action Test",
        "sender_email": f"action_{hash(message)%100000}@test.com",
        "message": message
    }
    r = client.post("/api/v1/enquiries", json=payload)
    assert r.status_code == 201
    return r.json()

def test_pending_not_executed_until_approve():
    data = _create_pending_enquiry("Test pending execution sales lead")
    action = data["proposed_action"]
    assert action["status"] == "PENDING_APPROVAL"
    # Verify not executed: check CRM contacts does not contain yet (or at least action not executed)
    # List actions pending should contain it
    r = client.get("/api/v1/actions?status=PENDING_APPROVAL")
    assert r.status_code == 200
    pending_ids = [a["id"] for a in r.json()]
    assert action["id"] in pending_ids

    # Verify via audit that no ACTION_EXECUTED yet
    r_audit = client.get(f"/api/v1/enquiries/{data['enquiry']['id']}/audit")
    # Should have ENQUIRY_RECEIVED, AI_ANALYSIS, ACTION_CREATED but not EXECUTED
    events = [e["event_type"] for e in r_audit.json()]
    assert "ACTION_CREATED" in events
    assert "ACTION_EXECUTED" not in events

def test_approve_executes_and_audit():
    import time
    msg = f"Approve me {time.time()}"
    data = _create_pending_enquiry(msg)
    aid = data["proposed_action"]["id"]
    # Approve
    r = client.post(f"/api/v1/actions/{aid}/approve", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "EXECUTED"
    # Audit should now have APPROVED and EXECUTED
    r_audit = client.get("/api/v1/audit?limit=100")
    assert r_audit.status_code == 200
    # Find our action audit
    logs = [l for l in r_audit.json() if l["entity_id"] == aid]
    types = [l["event_type"] for l in logs]
    assert "ACTION_APPROVED" in types
    assert "ACTION_EXECUTED" in types
    # Re-approve should fail
    r2 = client.post(f"/api/v1/actions/{aid}/approve", json={})
    assert r2.status_code == 400

def test_reject_never_executes():
    data = _create_pending_enquiry("Reject me test")
    aid = data["proposed_action"]["id"]
    r = client.post(f"/api/v1/actions/{aid}/reject", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "REJECTED"
    # Audit log reject
    r_audit = client.get("/api/v1/audit?limit=100")
    logs = [l for l in r_audit.json() if l["entity_id"] == aid]
    assert any(l["event_type"] == "ACTION_REJECTED" for l in logs)
    assert not any(l["event_type"] == "ACTION_EXECUTED" for l in logs)
    # Approve after reject should fail
    r2 = client.post(f"/api/v1/actions/{aid}/approve", json={})
    assert r2.status_code == 400
    # Reject again should fail
    r3 = client.post(f"/api/v1/actions/{aid}/reject", json={})
    assert r3.status_code == 400

def test_rejected_action_never_creates_crm():
    # Create and reject a lead, ensure no contact created
    r_before = client.get("/api/v1/crm/contacts")
    count_before = len(r_before.json())
    data = _create_pending_enquiry("Should be rejected and not create contact XYZ123")
    aid = data["proposed_action"]["id"]
    atype = data["proposed_action"]["action_type"]
    # Only lead/update would create contact
    r = client.post(f"/api/v1/actions/{aid}/reject", json={})
    assert r.status_code == 200
    r_after = client.get("/api/v1/crm/contacts")
    # If it was CREATE_LEAD, count should stay same
    if atype == "CREATE_LEAD":
        assert len(r_after.json()) == count_before

def test_approve_updates_crm_for_create_lead():
    r_before = client.get("/api/v1/crm/contacts")
    count_before = len(r_before.json())
    # Use unique email to ensure creation
    import time
    uniq = int(time.time()*1000) % 1000000
    payload = {
        "source": "email",
        "sender_name": "CRM Test",
        "sender_email": f"crm_{uniq}@example.com",
        "message": "We want to buy your product. Company CRMTestCo with 100 employees, budget 50k."
    }
    r = client.post("/api/v1/enquiries", json=payload)
    assert r.status_code == 201
    aid = r.json()["proposed_action"]["id"]
    atype = r.json()["proposed_action"]["action_type"]
    # Approve
    r_approve = client.post(f"/api/v1/actions/{aid}/approve", json={})
    assert r_approve.status_code == 200
    if atype == "CREATE_LEAD":
        r_after = client.get("/api/v1/crm/contacts")
        assert len(r_after.json()) == count_before + 1
        # Check contact exists with email
        emails = [c["email"] for c in r_after.json()]
        assert f"crm_{uniq}@example.com" in emails

def test_list_actions_filter():
    # Ensure filtering works
    r = client.get("/api/v1/actions?status=PENDING_APPROVAL&limit=10")
    assert r.status_code == 200
    for a in r.json():
        assert a["status"] == "PENDING_APPROVAL"
    r2 = client.get("/api/v1/actions?status=EXECUTED&limit=10")
    assert r2.status_code == 200
    for a in r2.json():
        assert a["status"] == "EXECUTED"

def test_invalid_action_id():
    r = client.post("/api/v1/actions/nonexistent-id/approve", json={})
    assert r.status_code == 404
    r2 = client.post("/api/v1/actions/nonexistent-id/reject", json={})
    assert r2.status_code == 404
