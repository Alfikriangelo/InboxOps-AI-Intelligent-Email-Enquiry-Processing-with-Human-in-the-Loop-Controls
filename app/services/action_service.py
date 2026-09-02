"""
Action service - deterministic execution, human approval enforcement.
AI recommends; deterministic code executes only after approval.
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.database import ProposedAction, Enquiry, Contact, Company, AuditLog
from app.models.schemas import ActionTypeEnum, ActionStatusEnum
from app.services import audit_service
from app.services.duplicate_detector import normalize_email, normalize_phone, normalize_name, normalize_company
from app.core.config import settings
from app.core.logging import logger

# Allowed actions per spec
ALLOWED_ACTIONS = {e.value for e in ActionTypeEnum}

def create_proposed_action(
    db: Session,
    enquiry: Enquiry,
    analysis,
    duplicate_status: Optional[str] = None,
    duplicate_contact: Optional[Contact] = None,
) -> ProposedAction:
    """
    Create a pending approval action based on AI analysis + deterministic rules.
    """
    # Map AI recommended_action to allowed type; fallback based on classification
    recommended = getattr(analysis, "recommended_action", None)
    # analysis.recommended_action may be enum or string
    if hasattr(recommended, "value"):
        recommended = recommended.value
    if recommended not in ALLOWED_ACTIONS:
        # fallback mapping
        cls = getattr(analysis, "classification", "other")
        if hasattr(cls, "value"):
            cls = cls.value
        mapping = {
            "sales": ActionTypeEnum.CREATE_LEAD.value,
            "support": ActionTypeEnum.CREATE_SUPPORT_CASE.value,
            "junk": ActionTypeEnum.MARK_AS_JUNK.value,
            "insufficient_information": ActionTypeEnum.REQUEST_MORE_INFORMATION.value,
            "other": ActionTypeEnum.CREATE_LEAD.value,
        }
        recommended = mapping.get(cls, ActionTypeEnum.CREATE_LEAD.value)

    # Confidence check: low confidence still creates action but flags for human review (metadata)
    confidence = getattr(analysis, "confidence", None)
    low_conf_flag = confidence is not None and confidence < settings.CONFIDENCE_THRESHOLD

    # Determine if human approval required: ALL consequential actions require approval per spec
    # Even high confidence must not bypass approval
    requires_approval = True

    # If duplicate detected and action is CREATE_LEAD, human must review before merging
    if duplicate_status in ("exact_match", "possible_duplicate") and recommended == ActionTypeEnum.CREATE_LEAD.value:
        recommended = ActionTypeEnum.UPDATE_CONTACT.value if duplicate_status == "exact_match" else recommended

    # Option B routing: suggested_team derived deterministically via embedding from LLM keywords+intent (no manual lists)
    suggested_team = getattr(analysis, "suggested_team", None)
    if hasattr(suggested_team, "value"):
        suggested_team_val = suggested_team.value
    else:
        suggested_team_val = str(suggested_team) if suggested_team else None
    # Fallback to routing_service if not already set (e.g., direct mock without enrichment) — include source (Opsi A)
    if not suggested_team_val:
        try:
            from app.services.routing_service import route_team

            q = " ".join(getattr(analysis, "intent_keywords", []) or []) + " " + (getattr(analysis, "intent", "") or "")
            routed = route_team(
                q.strip() or getattr(analysis, "intent", "") or str(getattr(analysis, "classification", "other")),
                getattr(analysis, "classification", None),
                source=enquiry.source,
            )
            suggested_team_val = routed.value if hasattr(routed, "value") else str(routed)
        except Exception:
            suggested_team_val = "triage"
    # Resolve owner deterministically
    try:
        from app.services.routing_service import get_team_owner
        from app.models.schemas import TeamEnum

        team_enum = TeamEnum(suggested_team_val) if suggested_team_val else TeamEnum.triage
        assigned_owner = get_team_owner(team_enum)
    except Exception:
        assigned_owner = "owner_triage@beda.id"

    metadata = {
        "classification": getattr(analysis.classification, "value", str(analysis.classification)) if hasattr(analysis, "classification") else str(analysis.classification),
        "confidence": confidence,
        "low_confidence_flag": low_conf_flag,
        "missing_information": getattr(analysis, "missing_information", []),
        "intent": getattr(analysis, "intent", None),
        "intent_keywords": getattr(analysis, "intent_keywords", []),
        "priority": getattr(analysis, "priority", None).value if hasattr(getattr(analysis, "priority", None), "value") else getattr(analysis, "priority", None),
        "suggested_team": suggested_team_val,
        "assigned_owner": assigned_owner,
        "contact": getattr(analysis, "contact", {}).model_dump() if hasattr(getattr(analysis, "contact", {}), "model_dump") else getattr(analysis, "contact", {}),
        "company": getattr(analysis, "company", {}).model_dump() if hasattr(getattr(analysis, "company", {}), "model_dump") else getattr(analysis, "company", {}),
        "duplicate_status": duplicate_status,
        "duplicate_of": duplicate_contact.id if duplicate_contact else None,
        "source": enquiry.source,
    }

    draft = getattr(analysis, "draft_response", None)

    action = ProposedAction(
        enquiry_id=enquiry.id,
        action_type=recommended,
        status=ActionStatusEnum.PENDING_APPROVAL.value,
        requires_human_approval=requires_approval,
        confidence=confidence,
        duplicate_status=duplicate_status,
        draft_response=draft,
        metadata_=metadata,
    )
    db.add(action)
    db.flush()

    audit_service.log_event(
        db,
        entity_type="proposed_action",
        entity_id=action.id,
        event_type="ACTION_CREATED",
        actor_type="system",
        actor_id="system",
        metadata={"action_type": recommended, "enquiry_id": enquiry.id, "duplicate_status": duplicate_status},
    )

    if duplicate_status:
        audit_service.log_event(
            db,
            entity_type="enquiry",
            entity_id=enquiry.id,
            event_type="DUPLICATE_DETECTED",
            actor_type="system",
            actor_id="system",
            metadata={"duplicate_status": duplicate_status, "matched_contact_id": duplicate_contact.id if duplicate_contact else None},
        )

    return action

def approve_action(db: Session, action_id: str, actor_id: str = None) -> ProposedAction:
    actor_id = actor_id or settings.DEMO_ACTOR_ID
    action = db.query(ProposedAction).filter(ProposedAction.id == action_id).first()
    if not action:
        raise ValueError(f"Action {action_id} not found")
    if action.status != ActionStatusEnum.PENDING_APPROVAL.value:
        raise ValueError(f"Action {action_id} is not pending approval (current: {action.status})")

    # Permission check placeholder: in production, check RBAC
    # For demo, allow demo_user; log warning if unknown actor
    # (production would use auth middleware)

    # Mark approved first
    action.status = ActionStatusEnum.APPROVED.value
    db.flush()

    audit_service.log_event(
        db,
        entity_type="proposed_action",
        entity_id=action.id,
        event_type="ACTION_APPROVED",
        actor_type="human",
        actor_id=actor_id,
        metadata={"action_type": action.action_type},
    )

    # Execute deterministically
    try:
        execute_action(db, action)
        action.status = ActionStatusEnum.EXECUTED.value
        db.flush()
        audit_service.log_event(
            db,
            entity_type="proposed_action",
            entity_id=action.id,
            event_type="ACTION_EXECUTED",
            actor_type="system",
            actor_id="system",
            metadata={"action_type": action.action_type, "enquiry_id": action.enquiry_id},
        )
        logger.info(f"Action {action.id} executed successfully")
    except Exception as e:
        logger.error(f"Action {action.id} execution failed: {e}")
        action.status = ActionStatusEnum.FAILED.value
        action.failure_reason = str(e)
        db.flush()
        audit_service.log_event(
            db,
            entity_type="proposed_action",
            entity_id=action.id,
            event_type="ACTION_FAILED",
            actor_type="system",
            actor_id="system",
            metadata={"error": str(e), "action_type": action.action_type},
        )
        raise

    db.commit()
    db.refresh(action)
    return action

def reject_action(db: Session, action_id: str, actor_id: str = None) -> ProposedAction:
    actor_id = actor_id or settings.DEMO_ACTOR_ID
    action = db.query(ProposedAction).filter(ProposedAction.id == action_id).first()
    if not action:
        raise ValueError(f"Action {action_id} not found")
    if action.status != ActionStatusEnum.PENDING_APPROVAL.value:
        raise ValueError(f"Action {action_id} is not pending approval (current: {action.status})")

    action.status = ActionStatusEnum.REJECTED.value
    db.flush()

    audit_service.log_event(
        db,
        entity_type="proposed_action",
        entity_id=action.id,
        event_type="ACTION_REJECTED",
        actor_type="human",
        actor_id=actor_id,
        metadata={"action_type": action.action_type, "enquiry_id": action.enquiry_id},
    )
    db.commit()
    db.refresh(action)
    logger.info(f"Action {action.id} rejected")
    # Rejected actions must never execute - enforced by status check
    return action

def execute_action(db: Session, action: ProposedAction):
    """
    Deterministic CRM execution. Never called without human approval.
    """
    enquiry = db.query(Enquiry).filter(Enquiry.id == action.enquiry_id).first()
    if not enquiry:
        raise ValueError(f"Enquiry {action.enquiry_id} not found")

    meta = action.metadata_ or {}
    contact_data = meta.get("contact") or {}
    company_data = meta.get("company") or {}

    # Normalize helpers
    def get_contact_email():
        return contact_data.get("email") or enquiry.sender_email
    def get_contact_name():
        return contact_data.get("name") or enquiry.sender_name
    def get_phone():
        return contact_data.get("phone")
    def get_company_name():
        return company_data.get("name")

    if action.action_type == ActionTypeEnum.CREATE_LEAD.value:
        # Create company if needed
        company = None
        cname = get_company_name()
        if cname:
            norm_c = normalize_company(cname)
            company = db.query(Company).filter(Company.normalized_name == norm_c).first()
            if not company:
                company = Company(name=cname, normalized_name=norm_c, size=company_data.get("size"))
                db.add(company)
                db.flush()
        # Create contact
        email = get_contact_email()
        norm_email = normalize_email(email)
        phone = get_phone()
        norm_phone = normalize_phone(phone)
        name = get_contact_name()
        # Check not already exists (idempotency)
        existing = None
        if norm_email:
            existing = db.query(Contact).filter(Contact.normalized_email == norm_email).first()
        if not existing and norm_phone:
            existing = db.query(Contact).filter(Contact.normalized_phone == norm_phone).first()
        if existing:
            # Update existing instead of duplicate create
            logger.info(f"CREATE_LEAD found existing contact {existing.id}, updating")
            if name:
                existing.name = name
                existing.normalized_name = normalize_name(name)
            if phone:
                existing.phone = phone
                existing.normalized_phone = norm_phone
            contact = existing
        else:
            contact = Contact(
                company_id=company.id if company else None,
                name=name,
                normalized_name=normalize_name(name),
                email=email,
                normalized_email=norm_email,
                phone=phone,
                normalized_phone=norm_phone,
            )
            db.add(contact)
            db.flush()
        enquiry.contact_id = contact.id
        enquiry.processing_status = "COMPLETED"

    elif action.action_type == ActionTypeEnum.UPDATE_CONTACT.value:
        # Requires duplicate match; update that contact
        dup_id = meta.get("duplicate_of")
        contact = None
        if dup_id:
            contact = db.query(Contact).filter(Contact.id == dup_id).first()
        if not contact:
            # fallback: find by email
            norm_email = normalize_email(get_contact_email())
            if norm_email:
                contact = db.query(Contact).filter(Contact.normalized_email == norm_email).first()
        if not contact:
            raise ValueError("UPDATE_CONTACT: no matching contact found for update")
        # Update fields if provided
        name = contact_data.get("name")
        phone = contact_data.get("phone")
        cname = company_data.get("name")
        if name:
            contact.name = name
            contact.normalized_name = normalize_name(name)
        if phone:
            contact.phone = phone
            contact.normalized_phone = normalize_phone(phone)
        if cname:
            norm_c = normalize_company(cname)
            comp = db.query(Company).filter(Company.normalized_name == norm_c).first()
            if not comp:
                comp = Company(name=cname, normalized_name=norm_c, size=company_data.get("size"))
                db.add(comp)
                db.flush()
            contact.company_id = comp.id
        enquiry.contact_id = contact.id
        enquiry.processing_status = "COMPLETED"

    elif action.action_type == ActionTypeEnum.CREATE_SUPPORT_CASE.value:
        # Simulate support case creation: link enquiry to contact if exists
        email = get_contact_email()
        norm_email = normalize_email(email)
        contact = db.query(Contact).filter(Contact.normalized_email == norm_email).first() if norm_email else None
        if contact:
            enquiry.contact_id = contact.id
        # In real CRM, would create case record; here we just mark enquiry as completed with metadata
        enquiry.processing_status = "COMPLETED"
        # Store support case marker in action metadata
        if not action.metadata_:
            action.metadata_ = {}
        # keep

    elif action.action_type == ActionTypeEnum.REQUEST_MORE_INFORMATION.value:
        # No CRM mutation, just store draft and mark waiting
        enquiry.processing_status = "COMPLETED"
        # draft_response already stored in action

    elif action.action_type == ActionTypeEnum.MARK_AS_JUNK.value:
        enquiry.processing_status = "COMPLETED"
        # No contact created

    else:
        raise ValueError(f"Unknown action type: {action.action_type}")

    db.flush()
