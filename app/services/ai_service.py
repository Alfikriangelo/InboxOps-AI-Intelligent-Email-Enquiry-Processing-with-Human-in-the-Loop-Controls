"""
AI Service abstraction - LLM only reasons/recommends, never executes.

Gemini API via google-generativeai. Falls back to deterministic mock when no key.
Implements retry with exponential backoff, strict JSON parsing, Pydantic validation,
and cost-control (spam filter, input truncation) before calling LLM.
"""
import time
import json
import re
import logging
from typing import Optional

from pydantic import ValidationError

from app.core.config import settings
from app.models.schemas import AIAnalysis, ClassificationEnum, ActionTypeEnum
from app.core.logging import logger

# ---------- Prompt (optimized ~400 tokens: compact but explicit) ----------
SYSTEM_PROMPT = """You are InboxOps triage AI. Classify, extract, recommend. NEVER invent — use null if unknown.

Categories: sales (pricing/demo/partnership), support (help/bug/complaint), junk (spam), insufficient_information (too vague), other. Confidence 0-1, high only if clear.

Actions: CREATE_LEAD, UPDATE_CONTACT, CREATE_SUPPORT_CASE, REQUEST_MORE_INFORMATION, MARK_AS_JUNK.

Extract: contact{name,email,phone}, company{name,size e.g. "200 employees"}, intent(1 sentence), missing_information[budget,timeline,company,business_need,contact_details,phone,use_case,company_size], draft_response(≤3 sentences, null if junk, never promise send).

Rules: Return ONLY valid JSON, no markdown. No hallucinated company/phone/budget. If unsure, null + add to missing_information. missing_information is [] if none.

Schema: {"classification":"sales|support|junk|insufficient_information|other","confidence":0.0-1.0,"contact":{"name":str|null,"email":str|null,"phone":str|null},"company":{"name":str|null,"size":str|null},"intent":str|null,"missing_information":[str],"recommended_action":"CREATE_LEAD|UPDATE_CONTACT|CREATE_SUPPORT_CASE|REQUEST_MORE_INFORMATION|MARK_AS_JUNK","draft_response":str|null}

Example: {"classification":"sales","confidence":0.94,"contact":{"name":"John Smith","email":"john@acme.com","phone":null},"company":{"name":"Acme","size":"200 employees"},"intent":"Interested in AI automation for customer support","missing_information":["budget","timeline"],"recommended_action":"CREATE_LEAD","draft_response":"Thanks for reaching out, John. Happy to discuss Acme support automation — share timeline/budget?"}"""

# ---------- Deterministic filters (cost control: skip LLM for obvious cases) ----------
def is_obvious_spam(message: str) -> bool:
    low = message.lower()
    for kw in settings.SPAM_KEYWORDS:
        if kw.lower() in low:
            return True
    if len(low) < 15 and ("http://" in low or "https://" in low):
        return True
    return False

def deterministic_fast_path(sender_name: str, sender_email: str, message: str) -> Optional[AIAnalysis]:
    """Return AIAnalysis if message is clearly classifiable without LLM (high confidence).
    Saves RPM/RPD. Only bypass when very obvious; ambiguous goes to LLM."""
    low = message.lower().strip()
    # Vague / insufficient: short + vague phrase (up to 80 chars to catch "Hi, I'm interested in your services.")
    if len(low) < 80 and not any(k in low for k in ["price", "pricing", "demo", "support", "help", "issue", "bug", "error", "budget", "timeline"]):
        vague_phrases = ["interested in your services", "interested", "hello", "hi,", "more info", "tell me more"]
        if any(p in low for p in vague_phrases) or len(low.split()) < 7:
            return AIAnalysis(
                classification=ClassificationEnum.insufficient_information,
                confidence=0.91,
                contact={"name": sender_name, "email": sender_email, "phone": None},
                company={"name": None, "size": None},
                intent="Vague enquiry, insufficient details",
                missing_information=["company", "business_need", "contact_details"],
                recommended_action=ActionTypeEnum.REQUEST_MORE_INFORMATION,
                draft_response="Thanks for reaching out. Could you tell us a little more about your company and what problem you are looking to solve?",
            )
    # Strong support signals -> bypass LLM (high confidence)
    support_strong = ["can't log in", "cannot log in", "error 500", "not working", "broken", "refund", "ticket", "failed to", "help me"]
    if any(k in low for k in support_strong):
        m = re.search(r"(\+?\d[\d \-\(\)]{7,}\d)", message)
        phone = m.group(1).strip() if m else None
        return AIAnalysis(
            classification=ClassificationEnum.support,
            confidence=0.92,
            contact={"name": sender_name, "email": sender_email, "phone": phone},
            company={"name": None, "size": None},
            intent="Customer seeking support assistance",
            missing_information=[],
            recommended_action=ActionTypeEnum.CREATE_SUPPORT_CASE,
            draft_response=f"Thanks for contacting us, {sender_name or 'there'}. Our support team will look into the issue shortly.",
        )
    # Obvious sales: contains pricing/demo + budget/timeline/employees and not support_strong
    sales_strong = ["pricing", "quote", "demo", "proposal", "budget", "timeline"]
    if sum(1 for k in sales_strong if k in low) >= 2 and len(low) > 40 and "interested" not in low[:20]:
        # Require 2 sales keywords to avoid false positive on vague
        return None  # still ambiguous, let LLM decide
    # Support generic word "support" alone is ambiguous -> don't bypass, let LLM decide
    return None

def truncate_input(text: str, max_len: int = None) -> str:
    max_len = max_len or settings.MAX_INPUT_LENGTH
    if len(text) > max_len:
        return text[:max_len] + " ...[truncated]"
    return text

# ---------- Cache & Rate limiter (P1) ----------
import hashlib
_response_cache: dict[str, tuple[float, AIAnalysis]] = {}  # hash -> (timestamp, result)
_last_call_per_key: dict[int, float] = {}  # key_idx -> last_call_epoch
_key_quota_exhausted: dict[int, float] = {}  # key_idx -> expiry epoch (24h)

def _is_key_exhausted(key_idx: int) -> bool:
    exp = _key_quota_exhausted.get(key_idx)
    if exp and time.time() < exp:
        return True
    if exp and time.time() >= exp:
        _key_quota_exhausted.pop(key_idx, None)
    return False

def _mark_key_exhausted(key_idx: int):
    _key_quota_exhausted[key_idx] = time.time() + 86400  # 24h
    logger.warning(f"Marking Gemini key {key_idx+1} as quota-exhausted for 24h")

def _cache_key(sender_email: str, message: str, source: str) -> str:
    h = hashlib.sha256(f"{sender_email.strip().lower()}|{source}|{message.strip().lower()}".encode()).hexdigest()
    return h

def _get_cached(sender_email: str, message: str, source: str) -> Optional[AIAnalysis]:
    k = _cache_key(sender_email, message, source)
    entry = _response_cache.get(k)
    if entry:
        ts, val = entry
        if time.time() - ts < settings.CACHE_TTL_SECONDS:
            return val
        else:
            _response_cache.pop(k, None)
    return None

def _set_cached(sender_email: str, message: str, source: str, result: AIAnalysis):
    k = _cache_key(sender_email, message, source)
    # Simple LRU: keep max 500 entries
    if len(_response_cache) > 500:
        # evict oldest
        oldest = min(_response_cache.items(), key=lambda x: x[1][0])[0]
        _response_cache.pop(oldest, None)
    _response_cache[k] = (time.time(), result)

def _throttle_for_key(key_idx: int):
    """Enforce 5 RPM per key (12s). Sleep if needed before LLM call."""
    now = time.time()
    last = _last_call_per_key.get(key_idx, 0)
    elapsed = now - last
    min_interval = 60.0 / settings.RATE_LIMIT_RPM  # 12s for 5 RPM
    if elapsed < min_interval:
        sleep_for = min_interval - elapsed
        logger.info(f"Rate limiter: throttling key {key_idx+1} for {sleep_for:.1f}s (5 RPM)")
        time.sleep(sleep_for)
    _last_call_per_key[key_idx] = time.time()

# ---------- Gemini client abstraction ----------
class AIServiceError(Exception):
    pass

class AIService:
    def __init__(self):
        # Reload env in case .env changed after import (e.g., after user set key)
        # Use override=False so pytest monkeypatch (which sets GEMINI_API_KEY="") is respected
        try:
            from dotenv import load_dotenv
            load_dotenv(override=False)
            import os
            # Determine API keys list: respect explicit env var presence for test mock
            has_env_override = any(k in os.environ for k in ["GEMINI_API_KEY", "GEMINI_API_KEYS", "LLM_API_KEY", "LLM_API_KEYS", "GOOGLE_API_KEY"])
            if has_env_override:
                # Collect only from env (allows monkeypatch to force empty -> mock)
                env_keys: list[str] = []
                for ek in ["GEMINI_API_KEY", "GEMINI_API_KEYS", "LLM_API_KEY", "LLM_API_KEYS", "GOOGLE_API_KEY"]:
                    ev = os.getenv(ek, "")
                    if ev:
                        env_keys.extend([p.strip() for p in ev.split(",") if p.strip()])
                # Dedup
                seen = set()
                self.api_keys = [k for k in env_keys if not (k in seen or seen.add(k))]
                # If env explicitly set but empty -> mock (test)
                if not self.api_keys and any(os.getenv(k) == "" for k in ["GEMINI_API_KEY", "GEMINI_API_KEYS"] if k in os.environ):
                    self.api_keys = []
                elif not self.api_keys:
                    # No env keys but env var existed -> treat as mock anyway (empty)
                    # Fall back to settings only if truly no override and settings has keys
                    self.api_keys = []
                # Also include settings if env not forcing mock? For real runs, .env file not in os.environ initially, so has_env_override False -> use settings
                # When has_env_override and env_keys empty but settings has keys, we still want mock for tests -> don't add settings keys
                if self.api_keys:
                    # Has explicit env keys -> use them
                    pass
                else:
                    # Check if test intentionally set empty -> force mock, don't fallback to settings
                    if any(k in os.environ for k in ["GEMINI_API_KEY", "GEMINI_API_KEYS"]):
                        self.api_keys = []
                    else:
                        self.api_keys = settings.get_llm_api_keys()
            else:
                self.api_keys = settings.get_llm_api_keys()

            # Backward compat single key
            self.api_key = self.api_keys[0] if self.api_keys else ""

            if "GEMINI_MODEL" in os.environ or "LLM_MODEL" in os.environ:
                model_env = os.getenv("GEMINI_MODEL") or os.getenv("LLM_MODEL") or ""
                self.model_name = model_env.strip() if model_env else settings.get_llm_model()
            else:
                self.model_name = settings.get_llm_model()
        except Exception:
            self.api_keys = settings.get_llm_api_keys()
            self.api_key = self.api_keys[0] if self.api_keys else ""
            self.model_name = settings.get_llm_model()

        self.is_mock = not bool(self.api_keys)
        self._client = None
        self._client_type = None  # "genai" or "google-genai"
        self._current_key_index = 0
        if not self.is_mock:
            # Init with first key; rotation will re-configure per call if needed
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_keys[0])
                self._client = genai
                self._client_type = "genai"
                logger.info(f"Gemini AI initialized with model {self.model_name} ({len(self.api_keys)} key(s), google-generativeai)")
            except Exception as e1:
                try:
                    from google import genai as new_genai
                    self._client = new_genai.Client(api_key=self.api_keys[0])
                    self._client_type = "google-genai"
                    logger.info(f"Gemini AI initialized with model {self.model_name} ({len(self.api_keys)} key(s), google-genai)")
                except Exception as e2:
                    logger.warning(f"Failed to init Gemini (both SDKs): {e1} / {e2} — falling back to mock")
                    self.is_mock = True
                    self._client = None
        else:
            logger.info("AI Service running in MOCK mode (no GEMINI_API_KEY)")
            self.api_keys = []

    # Public entry with retry
    def analyse(self, sender_name: str, sender_email: str, message: str, source: str = "email") -> AIAnalysis:
        # cost control: spam filter first
        if is_obvious_spam(message):
            logger.info("Deterministic spam filter triggered, skipping LLM call")
            return AIAnalysis(
                classification=ClassificationEnum.junk,
                confidence=0.97,
                contact={"name": sender_name, "email": sender_email, "phone": None},
                company={"name": None, "size": None},
                intent="Detected as spam/junk via deterministic filter",
                missing_information=[],
                recommended_action=ActionTypeEnum.MARK_AS_JUNK,
                draft_response=None,
            )

        # Deterministic fast-path before LLM (saves RPM/RPD)
        fast = deterministic_fast_path(sender_name, sender_email, message)
        if fast is not None:
            logger.info(f"Deterministic fast-path hit: {fast.classification} (no LLM call)")
            return fast

        # Cache check before LLM (24h TTL)
        cached = _get_cached(sender_email, message, source)
        if cached is not None:
            logger.info(f"Cache hit for {sender_email} (no LLM call, saved RPM/RPD)")
            return cached

        truncated = truncate_input(message)

        # helper to parse retry_delay from Gemini error
        def _parse_retry_delay(err_msg: str) -> Optional[float]:
            m = re.search(r"retry in ([\d\.]+)s", err_msg, re.I)
            if m:
                try: return float(m.group(1))
                except: pass
            m = re.search(r"seconds:\s*(\d+)", err_msg, re.I)
            if m:
                try: return float(m.group(1))
                except: pass
            m = re.search(r"retry_delay.*?(\d+)", err_msg, re.I | re.S)
            if m:
                try: return float(m.group(1))
                except: pass
            return None

        # retry loop with quota vs rate differentiation
        last_err: Optional[Exception] = None
        for attempt in range(settings.MAX_RETRIES):
            try:
                raw = self._call_llm(sender_name, sender_email, truncated, source)
                validated = self._validate(raw)
                _set_cached(sender_email, message, source, validated)
                return validated
            except (ValidationError, json.JSONDecodeError, AIServiceError) as e:
                last_err = e
                msg = str(e).lower()
                is_quota = any(k in msg for k in ["perday", "prepayment", "generateRequestsPerDay".lower(), "quota_value: 20"])
                is_rate = "perminute" in msg or ("rate" in msg and "perminute" in msg) or "GenerateRequestsPerMinute".lower() in msg
                # If quota/RPD exhausted, don't retry with same keys — all keys already tried in _call_llm, fallback to mock immediately
                if is_quota or "prepayment" in msg:
                    logger.warning(f"AI quota/RPD exhausted (no retry), will fallback to mock after attempt {attempt+1}: {e}")
                    break
                # For rate (RPM), respect retry_delay from API instead of fixed backoff
                if is_rate or "429" in msg:
                    retry_delay = _parse_retry_delay(str(e))
                    # Prefer API delay, else 12s per RPM limit (5 RPM = 12s)
                    delay = retry_delay if retry_delay and retry_delay < 60 else 12.0
                    # On last attempt, don't sleep, will fallback or raise
                    if attempt < settings.MAX_RETRIES - 1:
                        logger.info(f"Rate limited (429), retrying in {delay}s (API delay)...")
                        time.sleep(delay)
                        continue
                    else:
                        break
                # For validation / other retryable, exponential backoff
                logger.warning(f"AI attempt {attempt+1}/{settings.MAX_RETRIES} failed: {e}")
                if attempt < settings.MAX_RETRIES - 1:
                    delay = settings.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    break
            except Exception as e:
                last_err = e
                logger.warning(f"AI unexpected error attempt {attempt+1}: {e}")
                if attempt < settings.MAX_RETRIES - 1:
                    delay = settings.RETRY_BASE_DELAY * (2 ** attempt)
                    time.sleep(delay)
                else:
                    break

        # all retries failed - fallback to mock for quota/billing OR invalid JSON to keep demo usable
        if last_err and any(k in str(last_err).lower() for k in ["429", "quota", "exhausted", "prepayment", "unterminated", "expecting", "json", "validation"]):
            logger.warning(f"Fallback to mock after retries ({type(last_err).__name__}): {last_err}")
            try:
                mock_raw = self._mock_analyse(sender_name, sender_email, truncated, source)
                validated = self._validate(mock_raw)
                _set_cached(sender_email, message, source, validated)
                return validated
            except Exception as me:
                logger.error(f"Mock fallback also failed: {me}")
        raise AIServiceError(f"AI analysis failed after {settings.MAX_RETRIES} retries: {last_err}")

    def _configure_client_for_key(self, api_key: str):
        """Re-configure generative AI client for the given key (for rotation)."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._client = genai
            self._client_type = "genai"
            return True
        except Exception as e1:
            try:
                from google import genai as new_genai
                self._client = new_genai.Client(api_key=api_key)
                self._client_type = "google-genai"
                return True
            except Exception as e2:
                logger.warning(f"Failed to configure client for rotated key: {e1} / {e2}")
                return False

    def _call_llm(self, sender_name: str, sender_email: str, message: str, source: str) -> dict:
        if self.is_mock:
            return self._mock_analyse(sender_name, sender_email, message, source)

        # If all keys quota-exhausted, skip LLM entirely (0 RPD)
        if self.api_keys and all(_is_key_exhausted(i) for i in range(len(self.api_keys))):
            raise AIServiceError("All Gemini keys quota-exhausted (24h), using mock fallback")

        candidates = [self.model_name]
        for fb in ["gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            if fb not in candidates:
                candidates.append(fb)

        last_err = None
        # Rotate through all available API keys when hitting quota (20/day per key -> 40/day with 2 keys)
        keys_to_try = self.api_keys if self.api_keys else [self.api_key]
        # Filter out quota-exhausted keys for this call (0 RPD if all exhausted)
        active_keys = [(i, k) for i, k in enumerate(keys_to_try) if not _is_key_exhausted(i)]
        if not active_keys:
            raise AIServiceError("All Gemini keys quota-exhausted (24h), using mock fallback")
        for key_idx, api_key in active_keys:
            # Rate limiter: 5 RPM per key = 12s min interval (only for active keys)
            _throttle_for_key(key_idx)
            if key_idx != self._current_key_index:
                logger.info(f"Rotating to Gemini key {key_idx+1}/{len(keys_to_try)} due to previous quota")
                if not self._configure_client_for_key(api_key):
                    continue
                self._current_key_index = key_idx
            for model_name in candidates:
                try:
                    if self._client_type == "google-genai":
                        from google.genai import types
                        prompt = f"""{SYSTEM_PROMPT}

Source: {source}
Sender: {sender_name} <{sender_email}>
Message:
{message}

Return ONLY JSON per schema."""
                        resp = self._client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.2,
                                top_p=0.9,
                                max_output_tokens=settings.MAX_OUTPUT_TOKENS,
                                response_mime_type="application/json",
                            ),
                        )
                        text = resp.text if hasattr(resp, "text") and resp.text else str(resp)
                        text = self._strip_code_fences(text)
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError as je:
                            logger.warning(f"JSON parse failed (genai), raw: {text[:500]!r} err: {je}")
                            m = re.search(r"\{.*\}", text, re.DOTALL)
                            if m:
                                data = json.loads(m.group(0))
                            else:
                                raise
                        if key_idx > 0:
                            logger.info(f"Gemini key rotation succeeded on key {key_idx+1}")
                        if model_name != self.model_name:
                            logger.info(f"Gemini fallback model succeeded: {model_name}")
                        return data
                    else:
                        import google.generativeai as genai
                        combined_prompt = f"""{SYSTEM_PROMPT}

Source: {source}
Sender: {sender_name} <{sender_email}>
Message:
{message}

Return ONLY valid JSON per schema. No markdown, no explanation, escape quotes in strings."""
                        try:
                            model = genai.GenerativeModel(
                                model_name,
                                generation_config={
                                    "temperature": 0.1,
                                    "top_p": 0.9,
                                    "max_output_tokens": settings.MAX_OUTPUT_TOKENS,
                                },
                            )
                            resp = model.generate_content(combined_prompt)
                        except Exception as e:
                            logger.warning(f"Generation config failed for {model_name}: {e} — retrying bare")
                            model = genai.GenerativeModel(model_name)
                            resp = model.generate_content(combined_prompt)
                        text = self._extract_text(resp)
                        text = self._strip_code_fences(text)
                        # Robust JSON extraction: find first { to last }
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError as je:
                            logger.warning(f"JSON parse failed, raw (first 500 chars): {text[:500]!r} error: {je}")
                            # Try to extract JSON object via regex
                            m = re.search(r"\{.*\}", text, re.DOTALL)
                            if m:
                                try:
                                    data = json.loads(m.group(0))
                                except:
                                    # Try fixing common issues: trailing commas, single quotes
                                    fixed = m.group(0).replace("'", '"').replace(",}", "}").replace(",]", "]")
                                    data = json.loads(fixed)
                            else:
                                raise
                        if key_idx > 0:
                            logger.info(f"Gemini key rotation succeeded on key {key_idx+1}")
                        if model_name != self.model_name:
                            logger.info(f"Gemini fallback model succeeded: {model_name}")
                        return data
                except json.JSONDecodeError:
                    raise
                except Exception as e:
                    msg = str(e).lower()
                    if "404" in msg or "not found" in msg or "unsupported" in msg or "not supported" in msg:
                        logger.warning(f"Model {model_name} not available: {e} — trying fallback")
                        last_err = e
                        continue
                    if "429" in msg or "quota" in msg or "rate" in msg or "prepayment" in msg:
                        is_quota = any(k in msg for k in ["perday", "preday", "prepayment", "quota", "generateRequestsPerDay".lower()])
                        if is_quota:
                            _mark_key_exhausted(key_idx)
                        # Quota hit for this key -> break model loop and try next key
                        logger.warning(f"{'Quota' if is_quota else 'Rate'} hit on key {key_idx+1}/{len(keys_to_try)} for model {model_name}: {e}")
                        last_err = AIServiceError(f"Retryable LLM error: {e}")
                        break  # break model loop -> outer key loop will continue to next key
                    if "timeout" in msg or "deadline" in msg:
                        raise AIServiceError(f"Retryable LLM error: {e}") from e
                    if "404" in msg or "not found" in msg:
                        last_err = e
                        continue
                    raise AIServiceError(f"LLM call failed: {e}") from e
            # If we broke due to 429, continue to next key; otherwise models exhausted for this key
            if last_err and isinstance(last_err, AIServiceError) and "429" in str(last_err).lower():
                # Continue to next key (if any)
                if key_idx < len(keys_to_try) - 1:
                    continue
                else:
                    # All keys exhausted with quota
                    raise last_err
        raise AIServiceError(f"All Gemini keys/models failed. Last error: {last_err}")

    def _extract_text(self, resp) -> str:
        # google-generativeai response handling
        try:
            if hasattr(resp, "text") and resp.text:
                return resp.text
            # fallback: candidates
            if hasattr(resp, "candidates") and resp.candidates:
                parts = resp.candidates[0].content.parts
                return "".join(p.text for p in parts if hasattr(p, "text"))
            return str(resp)
        except Exception as e:
            raise AIServiceError(f"Failed to extract LLM text: {e}") from e

    def _strip_code_fences(self, text: str) -> str:
        t = text.strip()
        # remove ```json ... ``` or ``` ... ```
        if t.startswith("```"):
            # find first newline after opening fence and last fence
            t = re.sub(r"^```(?:json)?\s*", "", t)
            t = re.sub(r"\s*```$", "", t)
        return t.strip()

    def _validate(self, data: dict) -> AIAnalysis:
        # Pydantic strict validation
        # Coerce confidence to float if needed
        if "confidence" in data and isinstance(data["confidence"], str):
            try:
                data["confidence"] = float(data["confidence"])
            except:
                pass
        analysis = AIAnalysis.model_validate(data)
        return analysis

    # ---------- Deterministic Mock ----------
    def _mock_analyse(self, sender_name: str, sender_email: str, message: str, source: str) -> dict:
        """
        Lightweight heuristic mock that mimics LLM behavior deterministically.
        Used when no API key is set, or for tests.
        """
        low = message.lower().strip()
        # Very short / vague -> insufficient_information
        if len(low) < 30 and not any(k in low for k in ["price", "pricing", "demo", "support", "help", "issue", "bug", "error"]):
            # Check if it's basically "hi interested"
            vague_phrases = ["interested in your services", "interested", "hello", "hi,", "more info", "tell me more"]
            if any(p in low for p in vague_phrases) or len(low.split()) < 8:
                return {
                    "classification": "insufficient_information",
                    "confidence": 0.91,
                    "contact": {"name": sender_name, "email": sender_email, "phone": None},
                    "company": {"name": None, "size": None},
                    "intent": "Vague enquiry, insufficient details",
                    "missing_information": ["company", "business_need", "contact_details"],
                    "recommended_action": "REQUEST_MORE_INFORMATION",
                    "draft_response": "Thanks for reaching out. Could you tell us a little more about your company and what problem you are looking to solve?",
                }
        # Signals
        sales_signals = ["interested", "pricing", "price", "quote", "demo", "automation for", "looking for", "partnership", "proposal", "budget", "timeline", "employees"]
        support_strong = ["issue", "bug", "error", "not working", "broken", "complaint", "refund", "ticket", "can't", "cannot", "help me", "not able", "failed to"]
        # If message is strongly support (has strong keywords) -> support, regardless of sales signals
        if any(k in low for k in support_strong):
            return {
                "classification": "support",
                "confidence": 0.88,
                "contact": {"name": sender_name, "email": sender_email, "phone": self._extract_phone(message)},
                "company": {"name": self._extract_company(message) or None, "size": self._extract_company_size(message)},
                "intent": "Customer seeking support assistance",
                "missing_information": [] if "error" in low or "issue" in low else ["order_id", "details"],
                "recommended_action": "CREATE_SUPPORT_CASE",
                "draft_response": f"Thanks for contacting us, {sender_name or 'there'}. We're sorry to hear you're having an issue and our support team will look into it shortly. Could you share any additional details or error messages?",
            }
        # Generic "support" / "help" alone is ambiguous; only treat as support if no strong sales signals
        support_generic = ["support", "help"]
        if any(k in low for k in support_generic) and not any(s in low for s in sales_signals):
            return {
                "classification": "support",
                "confidence": 0.82,
                "contact": {"name": sender_name, "email": sender_email, "phone": self._extract_phone(message)},
                "company": {"name": self._extract_company(message) or None, "size": self._extract_company_size(message)},
                "intent": "Customer seeking support assistance",
                "missing_information": ["details"],
                "recommended_action": "CREATE_SUPPORT_CASE",
                "draft_response": f"Thanks for contacting us, {sender_name or 'there'}. Our support team will look into your request shortly. Could you share additional details?",
            }
        # Junk signals (not caught by spam filter but still junk)
        junk_signals = ["lottery", "winner", "congratulations you won", "earn $", "make money fast"]
        if any(k in low for k in junk_signals):
            return {
                "classification": "junk",
                "confidence": 0.96,
                "contact": {"name": sender_name, "email": sender_email, "phone": None},
                "company": {"name": None, "size": None},
                "intent": "Spam/promotional content",
                "missing_information": [],
                "recommended_action": "MARK_AS_JUNK",
                "draft_response": None,
            }
        # Default -> sales
        company = self._extract_company(message)
        size = self._extract_company_size(message)
        missing = []
        if not company:
            missing.append("company")
        if "budget" not in low:
            missing.append("budget")
        if "timeline" not in low and "when" not in low:
            missing.append("timeline")
        # keep limited missing
        missing = missing[:3]
        intent = self._summarize_intent(message)
        return {
            "classification": "sales",
            "confidence": 0.94 if company else 0.78,
            "contact": {"name": sender_name, "email": sender_email, "phone": self._extract_phone(message)},
            "company": {"name": company, "size": size},
            "intent": intent,
            "missing_information": missing,
            "recommended_action": "CREATE_LEAD",
            "draft_response": f"Thanks for reaching out, {sender_name or 'there'}. We'd be happy to learn more about your requirements{f' at {company}' if company else ''}. Could you share your timeline and budget range?",
        }

    def _extract_phone(self, text: str) -> Optional[str]:
        m = re.search(r"(\+?\d[\d \-\(\)]{7,}\d)", text)
        if m:
            return m.group(1).strip()
        return None

    def _extract_company(self, text: str) -> Optional[str]:
        # naive: look for "at <Company>" or "from <Company>" or "company with ..." or capitalized words after "we are"
        m = re.search(r"\b(?:at|from|company|team at)\s+([A-Z][A-Za-z0-9 &]+)", text)
        if m:
            cand = m.group(1).strip().split(".")[0].split(",")[0].strip()
            # trim trailing common words
            cand = re.sub(r"\s+with\s+.*$", "", cand, flags=re.I).strip()
            if len(cand) > 1 and len(cand) < 50:
                return cand
        # fallback: look for "Acme" style - capitalized word before comma?
        return None

    def _extract_company_size(self, text: str) -> Optional[str]:
        m = re.search(r"(\d+\s*(?:employees|people|staff|members))", text, re.I)
        if m:
            return m.group(1)
        m2 = re.search(r"approximately\s+(\d+)", text, re.I)
        if m2:
            return f"{m2.group(1)} employees"
        return None

    def _summarize_intent(self, text: str) -> str:
        # first sentence or 120 chars
        s = text.strip().split(".")[0].strip()
        if len(s) > 120:
            s = s[:120].rsplit(" ", 1)[0] + "..."
        return s or "Business enquiry"

# Singleton
_ai_service: Optional[AIService] = None

def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service

def reset_ai_service(clear_cache: bool = False):
    global _ai_service, _response_cache, _key_quota_exhausted, _last_call_per_key
    _ai_service = None
    if clear_cache:
        _response_cache.clear()
        _key_quota_exhausted.clear()
        _last_call_per_key.clear()
