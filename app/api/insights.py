from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from collections import Counter

from app.models.database import get_db, Enquiry, ProposedAction
from app.models.schemas import AuditLogResponse

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])

@router.get("/summary")
def insights_summary(db: Session = Depends(get_db)):
    # counts by classification, by team, by priority, by source
    enquiries = db.query(Enquiry).all()
    actions = db.query(ProposedAction).all()

    by_classification = Counter(e.ai_classification or "unknown" for e in enquiries)
    by_source = Counter(e.source for e in enquiries)
    by_status = Counter(e.processing_status for e in enquiries)

    # team/priority from actions metadata
    by_team = Counter()
    by_priority = Counter()
    by_action_type = Counter(a.action_type for a in actions)
    by_action_status = Counter(a.status for a in actions)
    for a in actions:
        meta = a.metadata_ or {}
        if meta.get("suggested_team"):
            by_team[meta["suggested_team"]] += 1
        if meta.get("priority"):
            by_priority[meta["priority"]] += 1

    # missing info top
    missing_counter = Counter()
    for e in enquiries:
        out = e.ai_output or {}
        for m in out.get("missing_information", []) or []:
            missing_counter[m] += 1

    return {
        "total_enquiries": len(enquiries),
        "total_actions": len(actions),
        "by_classification": dict(by_classification),
        "by_source": dict(by_source),
        "by_status": dict(by_status),
        "by_team": dict(by_team),
        "by_priority": dict(by_priority),
        "by_action_type": dict(by_action_type),
        "by_action_status": dict(by_action_status),
        "top_missing_information": dict(missing_counter.most_common(5)),
    }

@router.get("/recent")
def insights_recent(limit: int = Query(default=10, le=50), source: Optional[str] = None, team: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Enquiry).order_by(Enquiry.created_at.desc())
    if source:
        q = q.filter(Enquiry.source == source)
    enquiries = q.limit(limit * 2).all()
    # filter by team if needed (check ai_output.suggested_team or action metadata)
    result = []
    for e in enquiries:
        # fetch latest action for this enquiry
        action = db.query(ProposedAction).filter(ProposedAction.enquiry_id == e.id).order_by(ProposedAction.created_at.desc()).first()
        meta = (action.metadata_ if action and action.metadata_ else {}) or {}
        suggested_team = (e.ai_output or {}).get("suggested_team") or meta.get("suggested_team")
        if team and suggested_team != team:
            continue
        result.append({
            "enquiry": {
                "id": e.id,
                "source": e.source,
                "sender_name": e.sender_name,
                "sender_email": e.sender_email,
                "message": e.message[:180],
                "ai_classification": e.ai_classification,
                "ai_confidence": e.ai_confidence,
                "duplicate_status": e.duplicate_status,
                "processing_status": e.processing_status,
                "created_at": e.created_at,
            },
            "insight": {
                "intent": (e.ai_output or {}).get("intent"),
                "intent_keywords": (e.ai_output or {}).get("intent_keywords", []),
                "priority": (e.ai_output or {}).get("priority"),
                "suggested_team": suggested_team,
                "assigned_owner": meta.get("assigned_owner"),
                "missing_information": (e.ai_output or {}).get("missing_information", []),
                "confidence": e.ai_confidence,
            },
            "action": {
                "id": action.id if action else None,
                "action_type": action.action_type if action else None,
                "status": action.status if action else None,
                "draft_response": action.draft_response if action else None,
                "metadata": meta,
            } if action else None,
        })
        if len(result) >= limit:
            break
    return result

@router.get("/enquiry/{enquiry_id}")
def enquiry_insight(enquiry_id: str, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    e = db.query(Enquiry).filter(Enquiry.id == enquiry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    actions = db.query(ProposedAction).filter(ProposedAction.enquiry_id == e.id).order_by(ProposedAction.created_at.desc()).all()
    # audit for this enquiry
    from app.models.database import AuditLog
    logs = db.query(AuditLog).filter(AuditLog.entity_id == e.id).order_by(AuditLog.created_at.desc()).limit(20).all()
    action_ids = [a.id for a in actions]
    if action_ids:
        alogs = db.query(AuditLog).filter(AuditLog.entity_id.in_(action_ids)).order_by(AuditLog.created_at.desc()).limit(20).all()
        logs = sorted(logs + alogs, key=lambda x: x.created_at, reverse=True)
    return {
        "enquiry": {
            "id": e.id,
            "source": e.source,
            "sender_name": e.sender_name,
            "sender_email": e.sender_email,
            "message": e.message,
            "ai_classification": e.ai_classification,
            "ai_confidence": e.ai_confidence,
            "ai_output": e.ai_output,
            "duplicate_status": e.duplicate_status,
            "processing_status": e.processing_status,
            "created_at": e.created_at,
        },
        "actions": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "status": a.status,
                "confidence": a.confidence,
                "draft_response": a.draft_response,
                "metadata": a.metadata_,
                "created_at": a.created_at,
            }
            for a in actions
        ],
        "audit": [
            {"event_type": l.event_type, "actor_type": l.actor_type, "actor_id": l.actor_id, "metadata": l.metadata_, "created_at": l.created_at}
            for l in logs[:20]
        ],
    }
