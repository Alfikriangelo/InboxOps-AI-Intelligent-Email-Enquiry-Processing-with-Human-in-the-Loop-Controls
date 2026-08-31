"""
Main enquiry processing flow:
  save_raw_enquiry -> ai analyse -> validate -> confidence check -> duplicate -> proposed action -> audit

Mirrors spec's example process_enquiry function. Deterministic code owns control.
"""
from sqlalchemy.orm import Session
from app.models.database import Enquiry
from app.models.schemas import AIAnalysis
from app.services.ai_service import get_ai_service, AIServiceError
from app.services import audit_service, duplicate_detector
from app.services.action_service import create_proposed_action
from app.core.config import settings
from app.core.logging import logger

def process_enquiry(db: Session, source: str, sender_name: str, sender_email: str, message: str):
    """
    Synchronous processing for MVP (spec allows sync; production could use queue/worker).
    Returns (enquiry, proposed_action)
    """
    # 1. Save raw enquiry
    enquiry = Enquiry(
        source=source,
        sender_name=sender_name.strip(),
        sender_email=sender_email.strip().lower(),
        message=message.strip(),
        processing_status="PENDING",
    )
    db.add(enquiry)
    db.flush()  # get ID
    logger.info(f"Enquiry saved: {enquiry.id}")

    audit_service.log_event(
        db,
        entity_type="enquiry",
        entity_id=enquiry.id,
        event_type="ENQUIRY_RECEIVED",
        actor_type="system",
        actor_id="system",
        metadata={"source": source, "sender_email": sender_email},
    )
    audit_service.log_event(
        db,
        entity_type="enquiry",
        entity_id=enquiry.id,
        event_type="AI_ANALYSIS_STARTED",
        actor_type="system",
        actor_id="system",
        metadata={},
    )

    # 2. AI Analysis with retry handled inside service
    try:
        ai_service = get_ai_service()
        analysis: AIAnalysis = ai_service.analyse(
            sender_name=sender_name,
            sender_email=sender_email,
            message=message,
            source=source,
        )
        # Validate already done in service; extra Pydantic validation safety
        # If needed, re-validate
        if not isinstance(analysis, AIAnalysis):
            analysis = AIAnalysis.model_validate(analysis)

    except AIServiceError as e:
        logger.error(f"AI analysis failed for enquiry {enquiry.id}: {e}")
        enquiry.processing_status = "FAILED"
        enquiry.ai_output = {"error": str(e)}
        db.flush()
        audit_service.log_event(
            db,
            entity_type="enquiry",
            entity_id=enquiry.id,
            event_type="AI_ANALYSIS_FAILED",
            actor_type="system",
            actor_id="system",
            metadata={"error": str(e)},
        )
        db.commit()
        return enquiry, None
    except Exception as e:
        logger.error(f"Unexpected AI error: {e}")
        enquiry.processing_status = "FAILED"
        enquiry.ai_output = {"error": str(e)}
        db.flush()
        audit_service.log_event(
            db,
            entity_type="enquiry",
            entity_id=enquiry.id,
            event_type="AI_ANALYSIS_FAILED",
            actor_type="system",
            actor_id="system",
            metadata={"error": str(e)},
        )
        db.commit()
        return enquiry, None

    # 3. Store validated AI output denormalized
    enquiry.ai_classification = analysis.classification.value if hasattr(analysis.classification, "value") else str(analysis.classification)
    enquiry.ai_confidence = analysis.confidence
    enquiry.ai_output = analysis.model_dump()
    # processing stays PENDING until action completes, but mark as completed for audit
    audit_service.log_event(
        db,
        entity_type="enquiry",
        entity_id=enquiry.id,
        event_type="AI_ANALYSIS_COMPLETED",
        actor_type="ai",
        actor_id=ai_service.model_name if not ai_service.is_mock else "mock",
        metadata={"classification": enquiry.ai_classification, "confidence": enquiry.ai_confidence},
    )

    # 4. Confidence threshold check (deterministic rule)
    # Even high confidence still requires human approval; low just flagged
    if analysis.confidence < settings.CONFIDENCE_THRESHOLD:
        logger.info(f"Low confidence {analysis.confidence} < {settings.CONFIDENCE_THRESHOLD} - flagged for human review")
        # Note is stored in proposed action metadata; still proceed to create action

    # 5. Duplicate detection (deterministic)
    duplicate_status, duplicate_contact = duplicate_detector.find_duplicate(
        db,
        email=analysis.contact.email or sender_email,
        phone=analysis.contact.phone,
        name=analysis.contact.name or sender_name,
        company=analysis.company.name if analysis.company else None,
    )
    enquiry.duplicate_status = duplicate_status or "none"
    if duplicate_contact:
        enquiry.duplicate_of_contact_id = duplicate_contact.id
    db.flush()

    # 6. Create proposed action (always PENDING_APPROVAL)
    proposed_action = create_proposed_action(
        db,
        enquiry=enquiry,
        analysis=analysis,
        duplicate_status=duplicate_status,
        duplicate_contact=duplicate_contact,
    )

    # 7. Mark enquiry as completed processing (action pending)
    enquiry.processing_status = "COMPLETED"
    db.flush()
    db.commit()
    db.refresh(enquiry)
    db.refresh(proposed_action)

    logger.info(f"Enquiry {enquiry.id} processed -> action {proposed_action.id} ({proposed_action.action_type})")

    return enquiry, proposed_action
