"""
Audit service - deterministic, append-only logging. Never stores secrets.
"""
from typing import Optional, Any
from sqlalchemy.orm import Session
from app.models.database import AuditLog, get_engine
from app.core.logging import logger
from datetime import datetime, timezone

# Event types per spec
EVENT_TYPES = [
    "ENQUIRY_RECEIVED",
    "AI_ANALYSIS_STARTED",
    "AI_ANALYSIS_COMPLETED",
    "AI_ANALYSIS_FAILED",
    "DUPLICATE_DETECTED",
    "ACTION_CREATED",
    "ACTION_APPROVED",
    "ACTION_REJECTED",
    "ACTION_EXECUTED",
    "ACTION_FAILED",
]

def log_event(
    db: Session,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor_type: str = "system",
    actor_id: str = "system",
    metadata: Optional[dict] = None,
) -> AuditLog:
    # sanitize metadata: never log secrets
    if metadata:
        sanitized = {}
        for k, v in metadata.items():
            lk = k.lower()
            if any(s in lk for s in ["key", "secret", "password", "token", "api"]):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = v
        metadata = sanitized

    entry = AuditLog(
        entity_type=entity_type,
        entity_id=str(entity_id),
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        metadata_=metadata or {},
    )
    db.add(entry)
    db.flush()  # get id without commit; caller controls transaction
    logger.info(f"AUDIT {event_type} {entity_type}:{entity_id} by {actor_type}:{actor_id}")
    return entry

def get_audit_logs(db: Session, entity_type: Optional[str] = None, entity_id: Optional[str] = None, event_type: Optional[str] = None, limit: int = 100):
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(AuditLog.entity_id == entity_id)
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    return q.limit(limit).all()

def get_all_logs(db: Session, limit: int = 200):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
