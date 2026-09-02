"""
FastAPI entrypoint. Demonstrates clear separation:
  - LLM recommends (ai_service)
  - Deterministic code validates, detects duplicates, enforces approval, executes
  - Human in loop required for consequential actions
"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.models.database import create_all_tables, get_db, get_engine
from app.models.schemas import HealthResponse
from app.api.enquiries import router as enquiries_router
from app.api.actions import router as actions_router
from app.api.teams import router as teams_router
from app.api.insights import router as insights_router

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (simple for MVP; production would use Alembic migrations)
    try:
        create_all_tables()
        logger.info("Database tables ensured")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        raise
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
InboxOps AI — Intelligent Email Enquiry Processing with Human-in-the-Loop Controls.

**Principle:** AI can reason and recommend, but consequential actions remain under deterministic control and require human approval.

- LLM only returns structured recommendations (classification, extraction, draft)
- Deterministic code validates, checks confidence, detects duplicates, enforces approval, executes CRM
- Audit log records every event

See /docs for interactive API. Frontend at NEXT.js (port 3000) consumes these endpoints.
""",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list if settings.cors_origins_list else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(enquiries_router)
app.include_router(actions_router)
app.include_router(teams_router)
app.include_router(insights_router)

# Health
@app.get("/health", response_model=HealthResponse, tags=["health"])
def health_check(db: Session = Depends(get_db)):
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"
    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        version=settings.APP_VERSION,
        environment=settings.ENV,
        mock_mode=settings.is_mock_mode,
        database=db_status,
    )

# Extra convenience endpoints for audit and CRM overview (not required but helpful for demo)
@app.get("/api/v1/audit", tags=["audit"])
def list_audit(limit: int = 100, db: Session = Depends(get_db)):
    from app.services.audit_service import get_all_logs
    logs = get_all_logs(db, limit=limit)
    from app.models.schemas import AuditLogResponse
    return [AuditLogResponse.model_validate(l).model_dump() for l in logs]

@app.get("/api/v1/crm/contacts", tags=["crm"])
def list_contacts(limit: int = 50, db: Session = Depends(get_db)):
    from app.models.database import Contact
    contacts = db.query(Contact).order_by(Contact.created_at.desc()).limit(limit).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "phone": c.phone,
            "company_id": c.company_id,
            "company": {"id": c.company.id, "name": c.company.name, "size": c.company.size} if c.company else None,
            "created_at": c.created_at,
        }
        for c in contacts
    ]

@app.get("/api/v1/crm/companies", tags=["crm"])
def list_companies(limit: int = 50, db: Session = Depends(get_db)):
    from app.models.database import Company
    companies = db.query(Company).order_by(Company.created_at.desc()).limit(limit).all()
    return [
        {"id": c.id, "name": c.name, "size": c.size, "created_at": c.created_at}
        for c in companies
    ]

@app.delete("/api/v1/crm/contacts/{contact_id}", status_code=204, tags=["crm"])
def delete_contact(contact_id: str, db: Session = Depends(get_db)):
    from app.models.database import Contact, Enquiry
    from app.services.audit_service import log_event
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Contact not found")
    # nullify enquiry references (contact_id & duplicate_of_contact_id)
    db.query(Enquiry).filter(Enquiry.contact_id == contact_id).update({Enquiry.contact_id: None}, synchronize_session=False)
    db.query(Enquiry).filter(Enquiry.duplicate_of_contact_id == contact_id).update({Enquiry.duplicate_of_contact_id: None}, synchronize_session=False)
    # delete audit logs for this contact
    from app.models.database import AuditLog
    db.query(AuditLog).filter(AuditLog.entity_id == contact_id).delete(synchronize_session=False)
    try:
        log_event(db, entity_type="contact", entity_id=contact_id, event_type="CONTACT_DELETED", actor_type="human", actor_id="demo_user", metadata={"email": contact.email})
    except Exception:
        pass
    db.delete(contact)
    db.commit()
    return None

@app.get("/", tags=["root"])
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
        "frontend": settings.FRONTEND_URL,
        "message": "InboxOps AI - LLM recommends, deterministic code controls, human approves.",
    }

# For `uvicorn app.main:app`
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
