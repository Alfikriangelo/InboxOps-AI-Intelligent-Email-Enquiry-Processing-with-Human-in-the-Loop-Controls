"""
Pydantic schemas for API validation and AI structured output validation.
"""
from enum import Enum
from typing import Optional, List, Any
from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict
from datetime import datetime

# ---------- Enums ----------
class SourceEnum(str, Enum):
    email = "email"
    website = "website"
    messaging = "messaging"

class ClassificationEnum(str, Enum):
    sales = "sales"
    support = "support"
    junk = "junk"
    insufficient_information = "insufficient_information"
    other = "other"

class ActionTypeEnum(str, Enum):
    CREATE_LEAD = "CREATE_LEAD"
    UPDATE_CONTACT = "UPDATE_CONTACT"
    CREATE_SUPPORT_CASE = "CREATE_SUPPORT_CASE"
    REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION"
    MARK_AS_JUNK = "MARK_AS_JUNK"

class ActionStatusEnum(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"

class ProcessingStatusEnum(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class DuplicateStatusEnum(str, Enum):
    none = "none"
    exact_match = "exact_match"
    possible_duplicate = "possible_duplicate"

# ---------- AI structured output ----------

class AIContact(BaseModel):
    name: Optional[str] = Field(default=None, description="Contact name or null if not available")
    email: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)

class AICompany(BaseModel):
    name: Optional[str] = Field(default=None)
    size: Optional[str] = Field(default=None, description="e.g. '200 employees' or null")

class AIAnalysis(BaseModel):
    """Strict schema the LLM must conform to."""
    classification: ClassificationEnum
    confidence: float = Field(ge=0.0, le=1.0)
    contact: AIContact = Field(default_factory=AIContact)
    company: AICompany = Field(default_factory=AICompany)
    intent: Optional[str] = Field(default=None, description="Brief intent summary or null")
    missing_information: List[str] = Field(default_factory=list)
    recommended_action: ActionTypeEnum
    draft_response: Optional[str] = Field(default=None, description="Draft reply, not auto-sent")

    @field_validator("missing_information", mode="before")
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            return []
        return v

    model_config = ConfigDict(extra="forbid")

# ---------- API request/response ----------

class EnquiryCreateRequest(BaseModel):
    source: SourceEnum
    sender_name: str = Field(min_length=1, max_length=255)
    sender_email: EmailStr
    message: str = Field(min_length=1, max_length=8000)

    @field_validator("sender_name", "message", mode="before")
    @classmethod
    def strip_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("message must not be empty")
        return v.strip()

class EnquiryResponse(BaseModel):
    id: str
    source: str
    sender_name: str
    sender_email: str
    message: str
    processing_status: str
    ai_classification: Optional[str] = None
    ai_confidence: Optional[float] = None
    ai_output: Optional[Any] = None
    duplicate_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ProposedActionResponse(BaseModel):
    id: str
    enquiry_id: str
    action_type: str
    status: str
    requires_human_approval: bool
    confidence: Optional[float] = None
    duplicate_status: Optional[str] = None
    draft_response: Optional[str] = None
    metadata: Optional[Any] = Field(default=None, validation_alias="metadata_", serialization_alias="metadata")
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Enriched enquiry for frontend convenience
    enquiry: Optional[EnquiryResponse] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class EnquiryCreateResponse(BaseModel):
    enquiry: EnquiryResponse
    proposed_action: Optional[ProposedActionResponse] = None
    duplicate_status: Optional[str] = None
    audit_logged: bool = True
    processing_status: str

class ActionApproveRequest(BaseModel):
    actor_id: Optional[str] = Field(default=None, description="Demo actor; production would use auth context")
    # No other fields; permissions would be checked via auth

class AuditLogResponse(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_type: str
    actor_id: str
    metadata: Optional[Any] = Field(default=None, validation_alias="metadata_", serialization_alias="metadata")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    mock_mode: bool
    database: str

