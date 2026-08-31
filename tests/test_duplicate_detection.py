from fastapi.testclient import TestClient
from app.main import app
from app.services.duplicate_detector import find_duplicate, normalize_email, normalize_phone, normalize_name, normalize_company

client = TestClient(app)

def test_normalization():
    assert normalize_email(" John@Acme.COM ") == "john@acme.com"
    assert normalize_phone("+1 (234) 567-8900") is not None
    assert normalize_name("  JOHN smith ") == "john smith"
    assert normalize_company("Acme Inc.") == "acme" or "acme" in normalize_company("Acme Inc.")

def test_exact_duplicate_via_api():
    # First enquiry creates pending lead
    payload1 = {
        "source": "email",
        "sender_name": "Alice Dup",
        "sender_email": "alice@dup.com",
        "message": "We need pricing for your platform. Budget 30k."
    }
    r1 = client.post("/api/v1/enquiries", json=payload1)
    assert r1.status_code == 201
    action1 = r1.json()["proposed_action"]
    assert r1.json()["duplicate_status"] in (None, "none")
    # Approve to create contact
    r_approve = client.post(f"/api/v1/actions/{action1['id']}/approve", json={})
    assert r_approve.status_code == 200
    assert r_approve.json()["status"] == "EXECUTED"

    # Second enquiry same email -> exact_match
    payload2 = {
        "source": "email",
        "sender_name": "Alice Dup",
        "sender_email": "alice@dup.com",
        "message": "Follow up on pricing for 50 seats."
    }
    r2 = client.post("/api/v1/enquiries", json=payload2)
    assert r2.status_code == 201
    data2 = r2.json()
    assert data2["duplicate_status"] == "exact_match"
    assert data2["proposed_action"]["duplicate_status"] == "exact_match"
    # Should propose UPDATE_CONTACT not CREATE_LEAD for exact match
    assert data2["proposed_action"]["action_type"] == "UPDATE_CONTACT"

def test_possible_duplicate_via_detector():
    from app.models.database import get_sessionmaker
    from app.models.database import Company, Contact

    # Reset DB with new in-memory for isolated test
    from app.models.database import override_engine_for_tests as oet
    oet("sqlite:///:memory:")
    from sqlalchemy.orm import Session
    SessionLocal = get_sessionmaker()
    db = SessionLocal()

    # Create company + contact
    comp = Company(name="Acme Corp", normalized_name=normalize_company("Acme Corp"))
    db.add(comp)
    db.flush()
    contact = Contact(
        company_id=comp.id,
        name="John Smith",
        normalized_name=normalize_name("John Smith"),
        email="john@acme.com",
        normalized_email=normalize_email("john@acme.com"),
        phone=None,
        normalized_phone=None,
    )
    db.add(contact)
    db.commit()

    # Same name different email, same company -> possible_duplicate
    status, matched = find_duplicate(
        db,
        email="john.smith+2@acme.com",  # different email
        phone=None,
        name="John Smith",
        company="Acme Corp",
    )
    assert status == "possible_duplicate"
    assert matched.id == contact.id

    # Different person same company but name exact? still possible
    status2, matched2 = find_duplicate(
        db,
        email="other@different.com",
        phone=None,
        name="John Smith",
        company=None,  # no company
    )
    # Name exact alone is considered possible_duplicate per design
    assert status2 == "possible_duplicate"

    # Totally different -> none
    status3, matched3 = find_duplicate(
        db,
        email="new@newco.com",
        phone="08123456789",
        name="Jane Doe",
        company="NewCo",
    )
    assert status3 is None
    assert matched3 is None

    db.close()

def test_duplicate_never_auto_merges():
    # Ensure duplicate detection does not merge; requires approval
    payload = {
        "source": "email",
        "sender_name": "Bob Merge",
        "sender_email": "bob@merge.com",
        "message": "Interested in demo."
    }
    r = client.post("/api/v1/enquiries", json=payload)
    assert r.status_code == 201
    action = r.json()["proposed_action"]
    # Should be pending, not executed
    assert action["status"] == "PENDING_APPROVAL"
    # Even if duplicate, we haven't approved - ensure contacts not merged automatically
    # List contacts should not have auto-created Bob until approved
    from app.models.database import get_sessionmaker
    # Count contacts before approve
    r_contacts_before = client.get("/api/v1/crm/contacts")
    count_before = len(r_contacts_before.json())
    # Not approved yet, so contact not in CRM
    # Approve
    client.post(f"/api/v1/actions/{action['id']}/approve", json={})
    r_contacts_after = client.get("/api/v1/crm/contacts")
    assert len(r_contacts_after.json()) >= count_before + 1
