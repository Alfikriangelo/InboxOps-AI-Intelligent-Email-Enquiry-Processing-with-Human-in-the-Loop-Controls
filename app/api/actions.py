from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.models.database import get_db, ProposedAction, Enquiry
from app.models.schemas import ProposedActionResponse
from app.services.action_service import approve_action, reject_action
from app.core.config import settings

router = APIRouter(prefix="/api/v1/actions", tags=["actions"])

class ActorPayload(BaseModel):
    actor_id: Optional[str] = None

@router.get("", response_model=List[ProposedActionResponse])
def list_actions(
    status: Optional[str] = Query(default=None, description="Filter by status: PENDING_APPROVAL, APPROVED, REJECTED, EXECUTED, FAILED"),
    action_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(ProposedAction).order_by(ProposedAction.created_at.desc())
    if status:
        q = q.filter(ProposedAction.status == status)
    if action_type:
        q = q.filter(ProposedAction.action_type == action_type)
    actions = q.offset(offset).limit(limit).all()
    result = []
    for a in actions:
        resp = ProposedActionResponse.model_validate(a)
        # enrich with enquiry
        enquiry = db.query(Enquiry).filter(Enquiry.id == a.enquiry_id).first()
        if enquiry:
            from app.models.schemas import EnquiryResponse
            resp.enquiry = EnquiryResponse.model_validate(enquiry)
        result.append(resp)
    return result

@router.get("/{action_id}", response_model=ProposedActionResponse)
def get_action(action_id: str, db: Session = Depends(get_db)):
    action = db.query(ProposedAction).filter(ProposedAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    resp = ProposedActionResponse.model_validate(action)
    enquiry = db.query(Enquiry).filter(Enquiry.id == action.enquiry_id).first()
    if enquiry:
        from app.models.schemas import EnquiryResponse
        resp.enquiry = EnquiryResponse.model_validate(enquiry)
    return resp

@router.post("/{action_id}/approve", response_model=ProposedActionResponse)
def approve(action_id: str, payload: Optional[ActorPayload] = None, db: Session = Depends(get_db)):
    actor_id = (payload.actor_id if payload and payload.actor_id else settings.DEMO_ACTOR_ID)
    try:
        action = approve_action(db, action_id, actor_id=actor_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {e}")
    resp = ProposedActionResponse.model_validate(action)
    enquiry = db.query(Enquiry).filter(Enquiry.id == action.enquiry_id).first()
    if enquiry:
        from app.models.schemas import EnquiryResponse
        resp.enquiry = EnquiryResponse.model_validate(enquiry)
    return resp

@router.post("/{action_id}/reject", response_model=ProposedActionResponse)
def reject(action_id: str, payload: Optional[ActorPayload] = None, db: Session = Depends(get_db)):
    actor_id = (payload.actor_id if payload and payload.actor_id else settings.DEMO_ACTOR_ID)
    try:
        action = reject_action(db, action_id, actor_id=actor_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    resp = ProposedActionResponse.model_validate(action)
    enquiry = db.query(Enquiry).filter(Enquiry.id == action.enquiry_id).first()
    if enquiry:
        from app.models.schemas import EnquiryResponse
        resp.enquiry = EnquiryResponse.model_validate(enquiry)
    return resp
