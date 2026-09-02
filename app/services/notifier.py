"""
Notifier stub — deterministic alert for 'alert the right person' requirement.

MVP: logs NOTIFICATION_QUEUED deterministically; never auto-sends external message.
Production: replace with webhook/Slack/email sender behind approval gate.
LLM never calls this directly; only deterministic code after ACTION_CREATED.
"""
from sqlalchemy.orm import Session
from app.services import audit_service
from app.core.logging import logger


def queue_notification(db: Session, enquiry_id: str, action_id: str, action_type: str, assigned_owner: str = None, suggested_team: str = None):
    """
    Queue a notification for human reviewer. Team/owner derived deterministically via routing_service (Option B).
    LLM supplies keywords; deterministic embedding maps to team → owner. Never LLM-direct.
    """
    meta = {"enquiry_id": enquiry_id, "action_type": action_type, "channel": "queue_dashboard"}
    if assigned_owner:
        meta["assigned_owner"] = assigned_owner
    if suggested_team:
        meta["suggested_team"] = suggested_team
    logger.info(f"Notifier queued for enquiry {enquiry_id} action {action_id} ({action_type}) team={suggested_team} owner={assigned_owner}")
    audit_service.log_event(
        db,
        entity_type="proposed_action",
        entity_id=action_id,
        event_type="NOTIFICATION_QUEUED",
        actor_type="system",
        actor_id="system",
        metadata=meta,
    )
    # Production hook: e.g., slack_webhook.send(action), email_queue.enqueue(...)
    # Never send externally binding communication without human approval — notifier only alerts reviewer.
