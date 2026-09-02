# Architecture Decision Records — InboxOps AI

## 1. Gemini 3.6 Flash as Primary LLM

**Decision:** Use `gemini-3.6-flash` (latest stable per Google API 2026) via `google-generativeai` with multi-key rotation + fallback to deterministic mock.

**Why:**
- API confirmed 2.0/1.5 are deprecated (`404 ... use gemini-3.6-flash`).
- Flash tier = cheapest + lowest latency; fits cost-control requirement.
- `google-generativeai==0.8.5` strict prompt + Pydantic validation instead of `response_mime_type`.
- Multi-key rotation with quota-exhausted marking (24h) and rate throttling.

**Alternatives considered:** `gpt-4o-mini`, local models. Rejected: spec asks for Gemini abstraction; provider swapping via `AIService` interface.

**Trade-off:** Mock mode when no key → tests remain offline/stable.

## 2. SQLite Default, PostgreSQL in Production

**Decision:** `DATABASE_URL=sqlite:///./inboxops.db` default; `postgresql+psycopg2` via env for prod. SQLAlchemy handles both.

**Why:** Spec requires PostgreSQL, but SQLite enables zero-setup local run and `sqlite:///:memory:` for tests.

## 3. Deterministic Duplicate Detection (No LLM Merging)

**Decision:** Exact match on normalized `email`/`phone`; possible duplicate via normalized `name` + `company` exact or `difflib.SequenceMatcher >0.85`. LLM never merges.

**Why:** Satisfies spec priority; simple, explainable, no hallucinations. Human must approve merges.

## 4. Always PENDING_APPROVAL

**Decision:** Every consequential action (`CREATE_LEAD`, `UPDATE_CONTACT`, etc.) starts as `PENDING_APPROVAL`, even at 0.95 confidence.

**Why:** Spec: “Even high-confidence results must not bypass human approval”.

**Trade-off:** More human clicks; could add auto-approve for `MARK_AS_JUNK` behind flag, but kept strict for assessment.

## 5. Sync Processing for MVP + Notifier Stub

**Decision:** `process_enquiry` runs synchronously inside `POST /enquiries`; alerting via deterministic `notifier.py` stub (`NOTIFICATION_QUEUED` log, no external send).

**Why:** Spec: “MVP can process synchronously … document that production could use Message Queue / Worker”. Keeps repo simple, no Kafka/K8s/Airflow. Email requirement “alert the right person” is satisfied synchronously via queue visibility + audit log; production would add `API → Queue → Worker → Notifier (webhook/Slack/email)` without changing approval gate.

**Trade-off:** Latency includes LLM call (~1-2s, throttled 12s if burst); production needs async + webhook.

## 6. Pydantic Strict Validation

**Decision:** `AIAnalysis` with `extra="forbid"`, `confidence 0.0-1.0`, enums. Validation after every LLM call; retry on failure. `EnquiryCreateRequest.message` validated `1-2000 chars` (aligned with `MAX_INPUT_LENGTH 2000` truncate).

**Why:** Prevents prompt-injection or malformed JSON from corrupting DB; forces `null` not hallucination; UI `maxLength 2000` matches backend.

## 7. Spam Filter + Fast-Path + Cache + Rate Limiter Before LLM

**Decision:** Deterministic `SPAM_KEYWORDS` → `junk` without LLM; `deterministic_fast_path` (vague <80 chars → `insufficient_information` 0.91, support_strong → `support` 0.92) without LLM; `hash(email|source|message)` 24h cache (max 500); `_throttle_for_key` per-key throttling.

**Why:** Cost control “Rules → Cheap LLM → Escalate only ambiguous” — saves calls on cache hits; prompt diet 800→400 tokens + `MAX_INPUT 2000` + `MAX_OUTPUT 800` controls input cost and prevents truncation.

## 8. Retry 3× Exponential Backoff (Spec-Compliant)

**Decision:** `MAX_RETRIES=3` with `1s/2s/4s` exponential backoff per spec, differentiated: quota → mark key exhausted 24h and rotate, rate limit → respect `retry_delay` header, invalid JSON → robust regex extract + fix and retry, then fallback to mock.

**Why:** Spec p.15 mandates 3 retries; earlier 2 was cost-saving but non-compliant. With cache/fast-path/throttle, 3 retries does not increase steady-state cost; fallback to mock ensures demo continuity (`201` not `500`), only if mock fails → `FAILED`.

## 9. Next.js Frontend (Minimal but Functional)

**Decision:** Next.js 14 App Router + Tailwind, minimal black & white, 5 tabs: Ingest (2000 char), Queue, Enquiries, Audit, CRM.

**Why:** Spec says “/docs is sufficient. Optional minimal HTML”. Polished but quick dashboard exercises approval workflow without distracting from backend. `NEXT_PUBLIC_API_URL` → FastAPI.

## 10. No Secret in Audit / Response + Research Deferred

**Decision:** `audit_service.log_event` redacts `key|secret|password|token|api`. API never returns keys. “Research missing information” (email: research or request) is **deliberately deferred** — MVP only does `REQUEST_MORE_INFORMATION` (draft clarification) deterministically; production research would be a deterministic enrichment tool behind approval, never autonomous LLM tool-use.

**Why:** Security requirement + principle “LLM recommends, deterministic controls, human approves” extends to research.

## 11. Deliberately Not Automated (One Thing)

**Decision:** Refuse to autonomously send externally binding communications or perform irreversible CRM changes without human approval — drafts never auto-sent, `CREATE_LEAD/UPDATE_CONTACT/CREATE_SUPPORT_CASE` only after `POST /approve`, `REJECTED` never executes, merge requires human, notifier only queues, research never auto-runs.

**Why:** Core safety principle; simple robust architecture outscores complicated autonomous agent.
