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
    # Supports multiple keys for rotation when one hits quota (20/day free tier -> 2 keys = 40/day)
    GEMINI_API_KEY: str = ""  # primary key; if empty, service runs in mock mode
    GEMINI_API_KEYS: str = ""  # comma-separated additional keys, e.g. "key1,key2"
    LLM_API_KEY: str = ""  # alias for compatibility
    LLM_API_KEYS: str = ""  # alias comma-separated
    GEMINI_MODEL: str = "gemini-3.6-flash"
    LLM_MODEL: str = "gemini-3.6-flash"

    # Deterministic rules
    CONFIDENCE_THRESHOLD: float = 0.85
    HIGH_CONFIDENCE: float = 0.85
    MAX_RETRIES: int = 2  # reduced from 3 to save RPM (was 3×6=18 calls, now 2×2=4 max)
    MAX_INPUT_LENGTH: int = 2000  # was 8000 (~2000 tokens) -> 2000 (~500 tokens) to save input tokens
    MAX_OUTPUT_TOKENS: int = 800  # cap draft + JSON, 350 truncated, 600 still risky for long drafts
    RETRY_BASE_DELAY: float = 1.0  # seconds, exponential backoff
    RATE_LIMIT_RPM: int = 5  # per key per model (Gemini free tier)
    RATE_LIMIT_RPD: int = 20  # per key per model per day
    CACHE_TTL_SECONDS: int = 86400  # 24h hash cache

    # Cost control - deterministic spam patterns (lowercase substrings)
    SPAM_KEYWORDS: list[str] = [
        "win lottery",
        "you have won",
        "prince needs",
        "nigerian prince",
        "viagra",
        "crypto giveaway",
        "double your money",
    ]

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
