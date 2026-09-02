"""
Central configuration via environment variables.
Never hardcode secrets. Use .env file locally, env vars in production.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App
    APP_NAME: str = "InboxOps AI"
    APP_VERSION: str = "0.1.0"
    ENV: str = "development"  # development | production | test
    DEBUG: bool = True

    # Database
    # Default uses SQLite for easy local run; set to PostgreSQL in production:
    # e.g. postgresql+psycopg2://user:pass@localhost:5432/inboxops
    DATABASE_URL: str = "sqlite:///./inboxops.db"
    # For tests the app can override with sqlite:///:memory:

    # LLM - Gemini 3.6 Flash (per user request; current stable)
    # Supports multiple keys for rotation
    GEMINI_API_KEY: str = ""  # primary key; if empty, service runs in mock mode
    GEMINI_API_KEYS: str = ""  # comma-separated additional keys, e.g. "key1,key2"
    LLM_API_KEY: str = ""  # alias for compatibility
    LLM_API_KEYS: str = ""  # alias comma-separated
    GEMINI_MODEL: str = "gemini-3.6-flash"
    LLM_MODEL: str = "gemini-3.6-flash"

    # Deterministic rules
    CONFIDENCE_THRESHOLD: float = 0.85
    HIGH_CONFIDENCE: float = 0.85
    MAX_RETRIES: int = 3  # per spec: 3 retries with 1s/2s/4s exponential backoff
    MAX_INPUT_LENGTH: int = 2000  # validated in EnquiryCreateRequest
    MAX_OUTPUT_TOKENS: int = 1200  # cap draft + JSON, 1200 to avoid truncation of LLM JSON
    RETRY_BASE_DELAY: float = 1.0  # seconds, exponential backoff
    RATE_LIMIT_RPM: int = 5  # per key per model
    RATE_LIMIT_RPD: int = 20  # per key per model per day
    CACHE_TTL_SECONDS: int = 86400  # 24h hash cache

    # Deprecated: SPAM_KEYWORDS kept only as fallback safety-net, LLM 100% now determines junk (Option B scalable, no manual lists)
    SPAM_KEYWORDS: list[str] = [
        "win lottery",
        "you have won",
        "prince needs",
        "nigerian prince",
        "viagra",
        "crypto giveaway",
        "double your money",
    ]

    # Real-world routing — scalable via LLM keywords + embedding (Option B). Add team = add entry here, no code change.
    TEAM_OWNERS: dict[str, str] = {
        "sales": "owner_sales@beda.id",
        "support": "owner_support@beda.id",
        "billing_finance": "owner_finance@beda.id",
        "partnership": "owner_partnership@beda.id",
        "operations": "owner_ops@beda.id",
        "marketing": "owner_marketing@beda.id",
        "hr": "owner_hr@beda.id",
        "legal": "owner_legal@beda.id",
        "triage": "owner_triage@beda.id",
    }

    TEAM_DESCRIPTIONS: dict[str, str] = {
        "sales": "sales pricing quote demo product purchase buying enterprise deal discount proposal NDA contract revenue client customer acquisition",
        "support": "support help bug error not working broken issue ticket login password refund complaint technical assistance troubleshooting helpdesk",
        "billing_finance": "billing invoice payment finance accounting charge price tax payroll budget cost subscription fee refund overdue",
        "partnership": "partnership collaboration reseller affiliate integration joint venture channel partner referral alliance ecosystem",
        "operations": "operations delivery logistics fulfillment supply chain inventory shipping warehouse fulfillment SLA onboarding",
        "marketing": "marketing campaign press media advertising promotion brand social content SEO event webinar",
        "hr": "hr recruitment hiring career job vacancy talent interview people culture onboarding employee opportunities openings application employment join team openings career",
        "legal": "legal compliance contract GDPR privacy terms NDA regulation policy liability agreement",
        "triage": "general unclear vague insufficient information triage other ambiguous",
    }

    ROUTING_SIMILARITY_THRESHOLD: float = 0.12  # below this → triage (tunable)
    LLM_ONLY_CLASSIFICATION: bool = True  # when True, skip deterministic spam/fast-path, LLM 100%

    # Frontend / CORS
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    # Demo auth (production would use RBAC / OAuth)
    DEMO_ACTOR_ID: str = "demo_user"
    DEMO_ACTOR_TYPE: str = "human"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_llm_api_key(self) -> str:
        # Return first key for backward compat (single-key callers)
        keys = self.get_llm_api_keys()
        return keys[0] if keys else ""

    def get_llm_api_keys(self) -> list[str]:
        # Collect all keys from env + settings, dedup preserve order
        raw_parts: list[str] = []
        # From settings fields
        for attr in ["GEMINI_API_KEY", "GEMINI_API_KEYS", "LLM_API_KEY", "LLM_API_KEYS"]:
            val = getattr(self, attr, "") or ""
            if val:
                # split by comma
                raw_parts.extend([p.strip() for p in val.split(",") if p.strip()])
        # From os env (covers monkeypatch/tests and direct env)
        for env_key in ["GEMINI_API_KEY", "GEMINI_API_KEYS", "LLM_API_KEY", "LLM_API_KEYS", "GOOGLE_API_KEY"]:
            env_val = os.getenv(env_key, "")
            if env_val:
                raw_parts.extend([p.strip() for p in env_val.split(",") if p.strip()])
        # Dedup preserve order
        seen = set()
        uniq = []
        for k in raw_parts:
            if k not in seen:
                seen.add(k)
                uniq.append(k)
        return uniq

    def get_llm_model(self) -> str:
        raw = self.GEMINI_MODEL or self.LLM_MODEL or "gemini-3.6-flash"
        # Keep as-is; Gemini 3.6 Flash is the current stable per API
        return raw.strip()

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.CORS_ORIGINS:
            return []
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_mock_mode(self) -> bool:
        return not bool(self.get_llm_api_key())

settings = Settings()

# Convenience constants for imports that expect module-level values
CONFIDENCE_THRESHOLD = settings.CONFIDENCE_THRESHOLD
HIGH_CONFIDENCE = settings.HIGH_CONFIDENCE
MAX_RETRIES = settings.MAX_RETRIES
MAX_INPUT_LENGTH = settings.MAX_INPUT_LENGTH
