# Architecture Decision Records — InboxOps AI

## 1. Gemini 3.6 Flash as Primary LLM

**Decision:** Use `gemini-3.6-flash` (latest stable per Google API 2026) via `google-generativeai` with fallback to deterministic mock.

**Why:**
- User explicitly requested 3.6 Flash; API confirmed 2.0/1.5 are deprecated (`404 ... use gemini-3.6-flash`).
- Flash tier = cheapest + lowest latency; fits cost-control requirement (small/efficient model for classification).
- `response_mime_type: application/json` not supported in `google-generativeai==0.8.5`; we avoid it and rely on strict prompt + Pydantic validation instead.

**Alternatives considered:** `gpt-4o-mini`, local models. Rejected: spec asks for Gemini abstraction; provider swapping is supported via `AIService` interface.

**Trade-off:** Mock mode when no key → tests remain offline/stable, but real reasoning requires key.

## 2. SQLite Default, PostgreSQL in Production

**Decision:** `DATABASE_URL=sqlite:///./inboxops.db` default; `postgresql+psycopg2` via env for prod. SQLAlchemy handles both.

**Why:** Spec requires PostgreSQL, but SQLite enables zero-setup local run and `sqlite:///:memory:` for tests. No code change needed to switch.

**Trade-off:** SQLite lacks some PG features (e.g., concurrent writes); acceptable for MVP.

## 3. Deterministic Duplicate Detection (No LLM Merging)

**Decision:** Exact match on normalized `email`/`phone`; possible duplicate via normalized `name` + `company` exact or `difflib.SequenceMatcher >0.85`. LLM never merges.

**Why:** Satisfies spec priority; simple, explainable, no hallucinations. Human must approve merges.

**Trade-off:** Less fuzzy than ML entity resolution; can be extended with pg_trgm or embedding later.

## 4. Always PENDING_APPROVAL

**Decision:** Every consequential action (`CREATE_LEAD`, `UPDATE_CONTACT`, etc.) starts as `PENDING_APPROVAL`, even at 0.95 confidence.

**Why:** Spec: “Even high-confidence results must not bypass human approval”. Principle visibility.

**Trade-off:** More human clicks; could add auto-approve for `MARK_AS_JUNK` later behind feature flag, but kept strict for assessment.

## 5. Sync Processing for MVP

**Decision:** `process_enquiry` runs synchronously inside `POST /enquiries`.

**Why:** Spec: “MVP can process synchronously … document that production could use Message Queue / Worker”. Keeps repo simple, no Kafka/K8s/Airflow.

**Trade-off:** Latency includes LLM call (~1-2s); production would need async + webhook polling.

## 6. Pydantic Strict Validation

**Decision:** `AIAnalysis` with `extra="forbid"`, `confidence 0.0-1.0`, enums. Validation after every LLM call; retry on failure.

**Why:** Prevents prompt-injection or malformed JSON from corrupting DB; forces `null` not hallucination.

## 7. Spam Filter Before LLM

**Decision:** Deterministic `SPAM_KEYWORDS` check short-circuits to `junk` without LLM.

**Why:** Cost control example from spec (“Rules → Cheap LLM → Escalate only ambiguous”).

## 8. Next.js Frontend (Minimal but Functional)

**Decision:** Next.js 14 App Router + Tailwind, dark operational theme, 5 tabs: Ingest, Queue, Enquiries, Audit, CRM.

**Why:** Spec says “Do not spend significant time building a frontend. /docs is sufficient. Optional minimal HTML”. We provide a polished but quick dashboard that exercises the approval workflow without distracting from backend. No extra backend needed; calls FastAPI via `NEXT_PUBLIC_API_URL`.

**Trade-off:** More code than raw Swagger, but demonstrates human-in-the-loop visibly.

## 9. No Secret in Audit / Response

**Decision:** `audit_service.log_event` redacts any metadata key containing `key|secret|password|token|api`. API never returns `GEMINI_API_KEY`.

**Why:** Security requirement.

## 10. Exponential Backoff 1s/2s/4s

**Decision:** `MAX_RETRIES=3`, `RETRY_BASE_DELAY=1.0`.

**Why:** Spec example exactly. Handles timeout/invalid JSON/rate-limit; after retries, `FAILED` status + audit retained.

