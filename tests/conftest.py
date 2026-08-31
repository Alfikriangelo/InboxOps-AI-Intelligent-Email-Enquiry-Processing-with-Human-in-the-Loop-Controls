import os
import pytest
from app.models.database import override_engine_for_tests
from app.services.ai_service import reset_ai_service

@pytest.fixture(autouse=True)
def isolate_db(monkeypatch):
    # Use fresh in-memory DB per test
    override_engine_for_tests("sqlite:///:memory:")
    # Force mock mode for tests to avoid Gemini quota / flakiness (clear all key variants)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEYS", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    reset_ai_service()
    yield
    reset_ai_service()
