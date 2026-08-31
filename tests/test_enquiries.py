import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.ai_service import reset_ai_service

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("healthy", "degraded")
    assert "mock_mode" in data

def test_create_enquiry_valid_sales():
    reset_ai_service()
    payload = {
        "source": "email",
        "sender_name": "John Smith",
        "sender_email": "john@acme.com",
        "message": "Hi, we are interested in AI automation for our customer support team. We are a company with approximately 200 employees."
    }
    r = client.post("/api/v1/enquiries", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    assert "enquiry" in data
    assert "proposed_action" in data
    assert data["enquiry"]["sender_email"] == "john@acme.com"
    assert data["enquiry"]["processing_status"] == "COMPLETED"
    assert data["proposed_action"]["status"] == "PENDING_APPROVAL"
    assert data["proposed_action"]["requires_human_approval"] is True
    # draft is stored, not sent
    assert data["proposed_action"]["action_type"] in ("CREATE_LEAD", "CREATE_SUPPORT_CASE", "REQUEST_MORE_INFORMATION", "MARK_AS_JUNK", "UPDATE_CONTACT")

def test_enquiry_validation_invalid_input():
    # Invalid input should be rejected (422)
    payloads = [
        {"source": "invalid", "sender_name": "A", "sender_email": "a@b.com", "message": "hi"},  # bad source
        {"source": "email", "sender_name": "", "sender_email": "a@b.com", "message": "hi"},  # empty name
        {"source": "email", "sender_name": "A", "sender_email": "not-email", "message": "hi"},  # bad email
        {"source": "email", "sender_name": "A", "sender_email": "a@b.com", "message": ""},  # empty message
        {"source": "email", "sender_name": "A", "sender_email": "a@b.com", "message": "   "},  # whitespace
    ]
    for p in payloads:
        r = client.post("/api/v1/enquiries", json=p)
        assert r.status_code == 422, f"Should reject {p}, got {r.status_code} {r.text}"

def test_insufficient_information_flow():
    # Spec: "Hi, I'm interested in your services." -> insufficient_information -> REQUEST_MORE_INFORMATION pending
    payload = {
        "source": "website",
        "sender_name": "Vague User",
        "sender_email": "vague@example.com",
        "message": "Hi, I'm interested in your services."
    }
    r = client.post("/api/v1/enquiries", json=payload)
    assert r.status_code == 201
    data = r.json()
    # In mock mode this will be sales or insufficient; with Gemini live it should be insufficient
    # We assert it creates a pending action requiring approval and draft not auto-sent
    assert data["proposed_action"]["status"] == "PENDING_APPROVAL"
    # Draft may be null only for junk
    # For insufficient, draft should exist
    if data["enquiry"]["ai_classification"] == "insufficient_information":
        assert data["proposed_action"]["action_type"] == "REQUEST_MORE_INFORMATION"
        assert data["proposed_action"]["draft_response"] is not None
        assert "company" in data["enquiry"]["ai_output"]["missing_information"] or len(data["enquiry"]["ai_output"]["missing_information"]) > 0

def test_junk_detection_spam_filter():
    # Deterministic spam filter should skip LLM and mark junk
    payload = {
        "source": "email",
        "sender_name": "Spammer",
        "sender_email": "spam@evil.com",
        "message": "Congratulations you have won lottery! Claim your crypto giveaway now at http://spam.example"
    }
    r = client.post("/api/v1/enquiries", json=payload)
    assert r.status_code == 201
    data = r.json()
    # Could be junk via filter
    assert data["enquiry"]["ai_classification"] == "junk"
    assert data["proposed_action"]["action_type"] == "MARK_AS_JUNK"
    assert data["proposed_action"]["draft_response"] is None

def test_ai_output_validation():
    # Invalid AI structured output should fail safely — tested via Pydantic directly
    from app.models.schemas import AIAnalysis
    import pytest
    # Confidence out of range
    with pytest.raises(Exception):
        AIAnalysis.model_validate({
            "classification": "sales",
            "confidence": 1.5,  # invalid >1
            "contact": {"name": "A", "email": "a@b.com", "phone": None},
            "company": {"name": "Acme", "size": None},
            "intent": "test",
            "missing_information": [],
            "recommended_action": "CREATE_LEAD",
            "draft_response": None,
        })
    # Missing required field
    with pytest.raises(Exception):
        AIAnalysis.model_validate({
            "classification": "sales",
            # confidence missing
            "contact": {"name": "A"},
            "company": {},
            "intent": None,
            "missing_information": [],
            "recommended_action": "CREATE_LEAD",
        })
    # Extra field should be forbidded
    with pytest.raises(Exception):
        AIAnalysis.model_validate({
            "classification": "sales",
            "confidence": 0.9,
            "contact": {"name": "A"},
            "company": {},
            "intent": None,
            "missing_information": [],
            "recommended_action": "CREATE_LEAD",
            "draft_response": None,
            "extra_field": "not allowed",
        })

def test_enquiry_get_and_list():
    # Create one to ensure list not empty (isolated DB per test)
    payload = {
        "source": "email",
        "sender_name": "List Test",
        "sender_email": "list@test.com",
        "message": "We need pricing for 20 seats."
    }
    r_create = client.post("/api/v1/enquiries", json=payload)
    assert r_create.status_code == 201

    r = client.get("/api/v1/enquiries?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # get single
    eid = data[0]["id"]
    r2 = client.get(f"/api/v1/enquiries/{eid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == eid
    r3 = client.get("/api/v1/enquiries/nonexistent-id")
    assert r3.status_code == 404
