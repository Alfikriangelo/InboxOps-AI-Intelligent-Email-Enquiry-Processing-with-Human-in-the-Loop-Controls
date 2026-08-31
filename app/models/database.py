"""
SQLAlchemy models & DB session.
Supports PostgreSQL in production and SQLite for local dev/tests.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    String, Text, Float, Boolean, DateTime, ForeignKey, JSON, Index, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

def _uuid() -> str:
    return str(uuid.uuid4())

def _now() -> datetime:
    return datetime.now(timezone.utc)

# ---------- Enums as plain strings for DB portability ----------

# Company
class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    size: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    normalized_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company", cascade="all, delete-orphan")

class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    normalized_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    normalized_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    normalized_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    company: Mapped[Optional[Company]] = relationship(back_populates="contacts")
    enquiries: Mapped[list["Enquiry"]] = relationship(back_populates="contact", foreign_keys="Enquiry.contact_id")

    __table_args__ = (
        Index("ix_contacts_email_norm", "normalized_email"),
        Index("ix_contacts_phone_norm", "normalized_phone"),
    )

class Enquiry(Base):
    __tablename__ = "enquiries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # email | website | messaging
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Processing state
    processing_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # PENDING | COMPLETED | FAILED
    # AI output (denormalized for quick access + full json)
    ai_classification: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    duplicate_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # none | exact_match | possible_duplicate
    duplicate_of_contact_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=True)

    # optional link to contact after execution
    contact_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    contact: Mapped[Optional[Contact]] = relationship(back_populates="enquiries", foreign_keys=[contact_id])
    duplicate_of_contact: Mapped[Optional[Contact]] = relationship(foreign_keys=[duplicate_of_contact_id])
    proposed_actions: Mapped[list["ProposedAction"]] = relationship(back_populates="enquiry", cascade="all, delete-orphan", foreign_keys="ProposedAction.enquiry_id")

class ProposedAction(Base):
    __tablename__ = "proposed_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    enquiry_id: Mapped[str] = mapped_column(String(36), ForeignKey("enquiries.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)  # CREATE_LEAD etc
    status: Mapped[str] = mapped_column(String(20), default="PENDING_APPROVAL", nullable=False, index=True)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duplicate_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    draft_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON metadata: missing_information, company, contact, intent, reason, etc for UI
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    enquiry: Mapped[Enquiry] = relationship(back_populates="proposed_actions")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)  # system | human | ai
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

# DB engine / session helpers
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

_engine = None
_SessionLocal = None

def get_engine():
    global _engine
    if _engine is None:
        url = settings.DATABASE_URL
        connect_args = {}
        # SQLite needs check_same_thread=False for FastAPI threading
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        _engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    return _engine

def get_sessionmaker():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal

def create_all_tables():
    Base.metadata.create_all(bind=get_engine())

def get_db() -> Session:
    SessionLocal = get_sessionmaker()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# For testing: allow overriding
def override_engine_for_tests(database_url: str = "sqlite:///:memory:"):
    global _engine, _SessionLocal
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    from sqlalchemy.pool import StaticPool
    # Use StaticPool for in-memory sqlite so all sessions share same DB
    if database_url == "sqlite:///:memory:":
        _engine = create_engine(
            database_url,
            connect_args=connect_args,
            poolclass=StaticPool,
            pool_pre_ping=True,
        )
    else:
        _engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    Base.metadata.create_all(bind=_engine)
    return _engine, _SessionLocal
