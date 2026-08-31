from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.database import get_db, Enquiry, ProposedAction, AuditLog
from app.models.schemas import EnquiryCreateRequest, EnquiryCreateResponse, EnquiryResponse, AuditLogResponse
from app.services.enquiry_processor import process_enquiry

router = APIRouter(prefix="/api/v1/enquiries", tags=["enquiries"])

@router.post("", response_model=EnquiryCreateResponse, status_code=201)
def create_enquiry(payload: EnquiryCreateRequest, db: Session = Depends(get_db)):
    """
    1. Validate request (Pydantic)
    2. Normalize data
    3. Store raw enquiry
    4. AI analysis (Gemini with retry + mock fallback)
    5. Validate AI output (Pydantic)
    6. Duplicate check (deterministic)
    7. Create proposed action (PENDING_APPROVAL)
    8. Return result
    LLM never directly executes actions.
    """
    enquiry, action = process_enquiry(
        db,
        source=payload.source.value,
        sender_name=payload.sender_name,
        sender_email=payload.sender_email,
        message=payload.message,
    )

    # Build responses
    enquiry_resp = EnquiryResponse.model_validate(enquiry)
    action_resp = None
    if action:
        # Need to include enquiry inside action for convenience? already have separate
        from app.models.schemas import ProposedActionResponse
        action_resp = ProposedActionResponse.model_validate(action)
        # attach enquiry for richer frontend
        action_resp.enquiry = enquiry_resp

    return EnquiryCreateResponse(
        enquiry=enquiry_resp,
        proposed_action=action_resp,
        duplicate_status=enquiry.duplicate_status,
        processing_status=enquiry.processing_status,
    )

@router.get("", response_model=List[EnquiryResponse])
def list_enquiries(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    source: Optional[str] = Query(default=None),
    classification: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Enquiry).order_by(Enquiry.created_at.desc())
    if source:
        q = q.filter(Enquiry.source == source)
    if classification:
        q = q.filter(Enquiry.ai_classification == classification)
    return q.offset(offset).limit(limit).all()

@router.get("/{enquiry_id}", response_model=EnquiryResponse)
def get_enquiry(enquiry_id: str, db: Session = Depends(get_db)):
    enquiry = db.query(Enquiry).filter(Enquiry.id == enquiry_id).first()
    if not enquiry:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    return enquiry

@router.get("/{enquiry_id}/actions", response_model=List[dict])
def get_enquiry_actions(enquiry_id: str, db: Session = Depends(get_db)):
    enquiry = db.query(Enquiry).filter(Enquiry.id == enquiry_id).first()
    if not enquiry:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    actions = db.query(ProposedAction).filter(ProposedAction.enquiry_id == enquiry_id).order_by(ProposedAction.created_at.desc()).all()
    # manual dict to avoid validation alias issues
    from app.models.schemas import ProposedActionResponse
    return [ProposedActionResponse.model_validate(a).model_dump(by_alias=True) for a in actions]

@router.get("/{enquiry_id}/audit", response_model=List[AuditLogResponse])
def get_enquiry_audit(enquiry_id: str, db: Session = Depends(get_db)):
    enquiry = db.query(Enquiry).filter(Enquiry.id == enquiry_id).first()
    if not enquiry:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    logs = db.query(AuditLog).filter(AuditLog.entity_id == enquiry_id).order_by(AuditLog.created_at.desc()).all()
    # also include action logs for this enquiry's actions
    action_ids = [a.id for a in db.query(ProposedAction.id).filter(ProposedAction.enquiry_id == enquiry_id).all()]
    if action_ids:
        action_logs = db.query(AuditLog).filter(AuditLog.entity_id.in_(action_ids)).order_by(AuditLog.created_at.desc()).all()
        logs = sorted(logs + action_logs, key=lambda x: x.created_at, reverse=True)
    return logs
