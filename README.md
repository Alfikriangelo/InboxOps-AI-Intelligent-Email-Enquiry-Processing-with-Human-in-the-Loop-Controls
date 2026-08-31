# InboxOps AI — Intelligent Email Enquiry Processing with Human-in-the-Loop Controls

**BEDA AI Systems Assessment — Working Prototype**

> **AI can reason and recommend, but consequential actions must remain under deterministic control and require human approval when appropriate.**

A small, robust prototype that ingests business enquiries (email/website/messaging), classifies them with **Gemini 3.6 Flash**, extracts structured information, detects duplicates deterministically, proposes an action, and enforces **human approval before any CRM mutation** — with full auditability, retry, and cost control. Frontend is **minimal black & white, English, friendly**.

---

## Problem

Small businesses receive unstructured enquiries across email, web forms, and messaging. Manually triaging is slow and error-prone; fully autonomous AI risks hallucinations, duplicate CRM records, and irreversible actions (creating contacts, sending externally binding emails).

**This prototype solves:**
- Automatic understanding & extraction without hallucination (`null` when unknown)
- Deterministic duplicate detection (no LLM merging)
- Confidence-gated human review
- Draft responses that are *never auto-sent*
- Audit trail for every event

Focus: **correct controls over autonomous behavior** — not more features, not Kafka/K8s/mega infra.

---

## Quick Start

### Backend (FastAPI)

```bash
# 1. Clone & env
cp .env.example .env
# edit .env: set GEMINI_API_KEYS as comma-separated (7 keys = 140 RPD) and GEMINI_MODEL=gemini-3.6-flash
# Example: GEMINI_API_KEYS=AQ.Ab8...,AQ.Ab8...
# DATABASE_URL defaults to sqlite:///./inboxops.db (use PostgreSQL in prod: postgresql+psycopg2://user:pass@host:5432/inboxops)

# 2. Install & run
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# -> http://localhost:8000/docs  (Swagger)
# -> http://localhost:8000/health  (shows mock_mode, keys count)
```

Without `GEMINI_API_KEYS`, the service runs in **deterministic mock mode** (heuristics, no API cost) — tests remain green offline (`tests/conftest.py` forces mock via `GEMINI_API_KEYS=""`).

### Frontend (Next.js — Minimal Black & White)

```bash
cd frontend
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                  # http://localhost:3000  — minimal UI: white bg, black text, no color
```

### Docker Compose (PostgreSQL)

```bash
# optional: run Postgres for prod-like env
docker-compose up -d   # else set DATABASE_URL=postgresql+psycopg2://...
```

---

## Architecture

```mermaid
flowchart TD
    A[Email / Website / Messaging] --> B[FastAPI Ingestion API]
    B --> C[Validation & Normalization]
    C --> D[(PostgreSQL)]
    C --> E[AI Analysis Service - Gemini 3.6 Flash]
    E --> F[Classification & Extraction]
    F --> G[Pydantic Validation]
    G --> H[Deterministic Rules]
    H --> I[Duplicate Detection]
    I --> J[Proposed Action]
    J --> K{Human Approval Required?}
    K -->|Yes| L[Pending Approval]
    L --> M[Human Reviewer - Minimal UI]
    M -->|Approve| N[Deterministic Action Executor]
    M -->|Reject| O[Rejected]
    N --> P[CRM Database Update]
    O --> Q[Audit Log]
    P --> Q
    E --> Q
```

**Detailed:** [`docs/architecture.md`](docs/architecture.md) • **Decisions:** [`docs/decisions.md`](docs/decisions.md)

---

## Data Flow

```
POST /api/v1/enquiries {source, sender_name, sender_email, message}
  │
  ├─ 1. Pydantic validate + normalize (strip, lowercase email, 2000 char limit — was 8000)
  ├─ 2. Save raw enquiry (enquiries table, processing_status=PENDING)
  ├─ 3. Audit ENQUIRY_RECEIVED + AI_ANALYSIS_STARTED
  ├─ 4. Deterministic spam filter? → if yes: junk without LLM (cost save)
  ├─ 5. Deterministic fast-path? → if vague (<80 chars) or support_strong ("can't log in", "error 500") → return without LLM (saves 40-60% RPM)
  ├─ 6. Cache hit? → hash(email|source|message) 24h TTL → return cached (0 RPM)
  ├─ 7. Rate limiter → 5 RPM per key = 12s min interval per key (7 keys = 35 RPM total)
  ├─ 8. Gemini 3.6 Flash (compact prompt ~400 tokens + max_output 800) → strict JSON
  ├─ 9. Pydantic validate AI output (extra="forbid", confidence 0.0-1.0); on invalid JSON/429: retry with rotation
  │     • 429 quota (RPD/prepayment) → mark key exhausted 24h, rotate to next key (no outer retry)
  │     • 429 rate (RPM) → respect retry_delay from API, else 12s
  │     • Unterminated/Expecting JSON → retry 1× then fallback to mock
  ├─10. On failure after retries → fallback to mock (not FAILED) for demo continuity + AI_ANALYSIS_COMPLETED(moq); audit cached
  ├─11. On success: store ai_classification/confidence/output; AI_ANALYSIS_COMPLETED
  ├─12. Confidence < 0.85? → flag low_confidence in metadata (still PENDING_APPROVAL)
  ├─13. Duplicate detection (exact phone/email → exact_match; name+company → possible_duplicate)
  ├─14. Create proposed_actions (status=PENDING_APPROVAL, requires_human_approval=true) + ACTION_CREATED + DUPLICATE_DETECTED
  └─15. Return {enquiry, proposed_action, duplicate_status}
        → Minimal UI shows draft, missing info, confidence badge
        → Human: POST /api/v1/actions/{id}/approve|reject
             • approve: check PENDING, log ACTION_APPROVED, deterministic execute (create company/contact etc), log ACTION_EXECUTED, status=EXECUTED
             • reject: status=REJECTED, ACTION_REJECTED, never executes
             • re-approve fails (400)
```

**Sync for MVP** — production could be `API → Queue → Worker → Async`.

---

## Model and Tool Choices

**Why LLM (Gemini 3.6 Flash)?**
- Understands unstructured free-text, classifies intent, extracts entities, identifies missing fields, drafts replies — tasks where rules fail.
- 3.6 Flash = latest stable (API confirms 2.0/1.5 no longer available `404 use 3.6-flash`), small/efficient, low latency, cheap; prompt instructs `null` when unknown to avoid hallucination.
- **Multi-key rotation (7 keys = 140 RPD, 35 RPM)** via `GEMINI_API_KEYS` comma-separated (`app/core/config.py:67`, `app/services/ai_service.py:352`): on `429 quota` mark key exhausted 24h and rotate, on `rate` respect `retry_delay`. Single-key fallback kept for backwards compat but deduped.
- Prompt compacted 800→400 tokens (`SYSTEM_PROMPT` `ai_service.py:20`) + `MAX_INPUT 2000` + `MAX_OUTPUT 800` to cut input cost 68%.
- Abstracted via `app/services/ai_service.py` (interface, not coupled); swap provider by replacing service.

**Why deterministic code?**
- Permissions, validation, confidence gate, duplicate detection, CRM writes, approval enforcement, retries, audit, secrets, cache, rate limiter — must be **reproducible, testable, auditable**, not probabilistic.

**Why PostgreSQL (via SQLAlchemy)?**
- Spec requirement; ACID, JSON columns for flexible metadata, indexes for email/phone. SQLite default for zero-setup local/tests — same SQLAlchemy models, no code fork.

**Why human approval?**
- Consequential actions (create contact, send email, merge records) are irreversible/binding. Human retains control; LLM only recommends.

**Why Next.js frontend (minimal)?**
- Spec: `/docs` suffices; optional minimal UI. We provide **minimal black & white, English, friendly** dashboard (New/Queue/History/Log/Contacts) — white bg, black text, no color, large whitespace — that *demonstrates* human-in-the-loop without AI slop.

**Why FastAPI + Pydantic + SQLAlchemy?**
- FastAPI: auto OpenAPI at `/docs`, Pydantic integration, async-ready.
- Pydantic: strict schema for both API inputs and AI outputs.
- SQLAlchemy 2.0: typed Mapped models, pool handling for PG & SQLite.

---

## LLM vs Deterministic Code

| Responsibility | LLM (Gemini 3.6 Flash) | Deterministic Code |
|---|:---:|:---:|
| Understand unstructured enquiry | **Yes** | No |
| Classification (`sales/support/junk/insufficient/other`) | **Yes** | Fast-path pre-filter (spam/fast-path) |
| Extract information (name/email/phone/company/size/intent) | **Yes** | **Validation** (Pydantic, null enforcement) |
| Identify missing information | **Yes** | Flag + surface to human |
| Recommend next action (`CREATE_LEAD` etc.) | **Yes** (suggestion) | **Controls** (maps to allowed enum, decides final type) |
| Draft response | **Yes** | **No send** — stores draft, human approves |
| Send externally binding communication | No | **Human approval required** |
| Duplicate detection | No | **Yes** (exact email/phone, possible name+company) |
| Permission / confidence checks | No | **Yes** (0.85 threshold, low-flag) |
| CRM writes (`contacts`, `companies`) | No | **Yes** (deterministic executor after approve) |
| Merge customer records | No | **No** — blocked; human review required |
| Retry / backoff / failure handling | No | **Yes** (2× + quota/rate split, JSON fallback to mock) |
| Cache (24h hash) / Rate limiter (12s) | No | **Yes** (`ai_service.py:92`) |
| Audit logging / secret handling | No | **Yes** |
| Access secrets | No | **Yes** (least privilege, 7 keys deduped, never in logs) |

---

## Failure Handling

- **Incomplete information** (`"Hi, I'm interested"`): Fast-path deterministic (<80 chars, vague) returns `insufficient_information` (0.91) without LLM, or Gemini returns same with `missing_information: ["company","business_need","contact_details"]`, `REQUEST_MORE_INFORMATION`, draft clarification — marked `PENDING_APPROVAL`, never auto-sent. Tested in mock + live.
- **Hallucination prevention**: Prompt says “return `null` when not available, never invent”. Pydantic `extra="forbid"` + `null` enforcement + validation retry; missing fields listed explicitly. Compact prompt still explicit.
- **Duplicate records**: Exact `email`/`phone` normalized → `exact_match` → propose `UPDATE_CONTACT`; `name+company` normalized/similarity → `possible_duplicate` → human review before merge; LLM cannot merge.
- **Model failure / invalid JSON / timeout / rate limit**: 
  - `Unterminated string` / `Expecting ','` at col 80-117 (LLM truncated) → robust JSON extract `re.search(r"\{.*\}", DOTALL)` + fix `'→"` + retry 1×, then fallback to mock (not error). User previously saw `{"error":"AI analysis failed after 2 retries: Unterminated string..."}` now fixed to `201` mock.
  - `429 quota` (RPD/prepayment) → mark key exhausted 24h, rotate to next key (7 keys), no outer retry, fallback to mock if all exhausted (0 RPD after).
  - `429 rate` (RPM) → respect `retry_delay` from API header, else 12s, then retry.
  - After retries `processing_status=FAILED` only if mock also fails; else `COMPLETED` with mock and `AI_ANALYSIS_COMPLETED`.
- **Low confidence**: `<0.85` flagged in `metadata.low_confidence_flag`; action still pending review.
- **Rejection**: `REJECTED` status; executor checks `PENDING_APPROVAL` only — rejected never executes (tested).

---

## Security

- **Secrets**: via `GEMINI_API_KEYS` (comma-separated, 7 keys), `GEMINI_MODEL`, `DATABASE_URL` in `.env` / env vars; `.env.example` placeholder; never hardcoded, never in responses/logs. `audit_service` redacts keys (`***REDACTED***`). Previous `GEMINI_API_KEY` single removed, now only `GEMINI_API_KEYS` (deduped).
- **Permissions**: `action_service.approve` checks `PENDING_APPROVAL`; placeholder `actor_id=demo_user` with comment that production uses RBAC/OAuth; least privilege (AI cannot access secrets, delete, merge, send, or use tools).
- **Sensitive data**: Email/phone normalized but not exposed beyond need; audit `metadata` sanitized.
- **Validation**: All inputs via `EnquiryCreateRequest` (EmailStr, 1-2000 chars after P0, source enum); AI output via `AIAnalysis`.
- **CORS**: Limited to `FRONTEND_URL` / `CORS_ORIGINS`.

---

## Cost and Latency

- **Rule-based filtering**: Spam keyword list → deterministic `junk` without LLM. **Fast-path** (`support_strong`, vague `<80`) → 40-60% bypass without LLM.
- **Cache**: `hash(email|source|message)` 24h TTL (`CACHE_TTL_SECONDS 86400`, max 500) → repeated demo messages cost 0 RPM/RPD (verified: second same `john@acme.com` → `Cache hit (no LLM call)`).
- **Rate limiter**: `5 RPM per key =12s` (`RATE_LIMIT_RPM 5`, `_throttle_for_key`), 7 keys = `35 RPM` total. Throttle before LLM call, not after 429.
- **Quota rotation**: `7×20=140 RPD` (was 40 with 2 keys). On `429 quota` mark 24h and rotate, next new unique after quota exhausted → `0 RPD` (skip LLM, mock).
- **Prompt & tokens**: `800→400` tokens prompt + `8000→2000` input + `800` max output (was 350 truncated) → ~68% input saving, output not truncated.
- **Efficient model**: Gemini 3.6 Flash (fast/cheap) for all; structure ready to escalate `Rules → Cheap LLM → Escalate ambiguous` (ambiguous `confidence<0.85` flagged, not auto-escalated).
- **Input limits**: `MAX_INPUT_LENGTH=2000` truncate before LLM.
- **Latency**: Sync MVP (~1-2s incl. LLM, throttled 12s if burst); production path noted as `Message Queue + Worker + Async`.

**Before vs After (1 system run):** `11 RPD / 6 RPM` (3 retries ×2 keys×3 models) → `1-2 RPD / 1 RPM` (1 attempt ×2 keys max, then cache/fast-path 0) — verified in `test_one_run.py`.

---

## Deliberately Not Automated

> **The system deliberately refuses to autonomously send externally binding communications or perform irreversible CRM changes without appropriate human approval.**

Specifically: LLM drafts are stored, never emailed; `CREATE_LEAD`/`UPDATE_CONTACT`/`CREATE_SUPPORT_CASE` execute only after `POST /actions/{id}/approve`; `REJECTED` never executes; merging requires human review; even with 7 keys and cache, quota-exhausted still falls back to mock, never auto-sends.

---

## Pseudocode — Approval Gate (Critical Part)

```python
# app/services/enquiry_processor.py:14 + ai_service.py:231 + action_service.py:78
def process_enquiry(enquiry):
    save_raw(enquiry)  # enquiries PENDING
    audit("ENQUIRY_RECEIVED")

    if is_obvious_spam(message):  # deterministic, 0 LLM
        analysis = junk(0.97)
    elif fast := deterministic_fast_path(message):  # 0 LLM
        analysis = fast
    elif cached := cache.get(hash(message)):  # 0 LLM
        analysis = cached
    else:
        throttle(key)  # 12s per 5 RPM
        analysis = gemini_3_6_flash(enquiry)  # LLM only
        validated = AIAnalysis.model_validate(analysis)  # extra="forbid"

    if validated.confidence < 0.85:
        flag_low_confidence()

    duplicate = find_duplicate(email, phone, name, company)  # deterministic

    proposed = create_action(
        enquiry, analysis, duplicate,
        status="PENDING_APPROVAL",  # even if 0.95
        requires_human_approval=True
    )
    audit("ACTION_CREATED")
    return proposed

# Human must approve:
# POST /actions/{id}/approve -> check PENDING -> deterministic execute -> audit EXECUTED
# POST /actions/{id}/reject  -> REJECTED (never executes)
```

---

## Prototype Scope

This repository **intentionally implements the critical control path** rather than building a full CRM or unnecessary infrastructure:

- ✅ Working FastAPI + PostgreSQL (SQLite dev) + AI abstraction (7-key rotation, cache, fast-path, rate limiter) + Pydantic validation + duplicate detection + human approval + deterministic executor + audit logs + tests + architecture docs + minimal Next.js dashboard
- ❌ Not built: real email sending, full RBAC, Kafka/K8s/Airflow, microservices, multi-agent, RAG/vector DB — all noted as “scalable path later” per spec.

Clear architecture > more features. Correct controls > autonomous AI.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/enquiries` | Ingest enquiry (validate→AI→duplicate→propose) |
| `GET` | `/api/v1/enquiries?source=&classification=` | List enquiries |
| `GET` | `/api/v1/enquiries/{id}` | Get enquiry |
| `GET` | `/api/v1/enquiries/{id}/actions` | Actions for enquiry |
| `GET` | `/api/v1/enquiries/{id}/audit` | Audit for enquiry |
| `GET` | `/api/v1/actions?status=PENDING_APPROVAL` | List actions (pending queue) |
| `GET` | `/api/v1/actions/{id}` | Get action |
| `POST` | `/api/v1/actions/{id}/approve` | Human approve → execute |
| `POST` | `/api/v1/actions/{id}/reject` | Human reject (never executes) |
| `GET` | `/api/v1/audit?limit=` | Recent audit logs |
| `GET` | `/api/v1/crm/contacts` | List contacts (CRM simulation) |
| `GET` | `/api/v1/crm/companies` | List companies |
| `GET` | `/health` | `{status, version, environment, mock_mode, database}` |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/` | Root info |

**Example request:**

```bash
curl -X POST http://localhost:8000/api/v1/enquiries \
  -H "Content-Type: application/json" \
  -d '{"source":"email","sender_name":"John Smith","sender_email":"john@acme.com","message":"Hi, we are interested in AI automation for our customer support team. We are a company with approximately 200 employees."}'
```

**Example response:** `enquiry.ai_classification=sales (0.95)`, `duplicate_status=none`, `proposed_action={CREATE_LEAD, PENDING_APPROVAL, draft_response: "Thank you..."}`
On quota/JSON error now returns `201` with mock fallback (not `500`).

---

## Repository Structure

```
├── app/main.py                # FastAPI, CORS, /health
├── app/api/{enquiries,actions}.py
├── app/core/{config,logging}.py
├── app/models/{database,schemas}.py
├── app/services/{ai_service,enquiry_processor,duplicate_detector,action_service,audit_service}.py
├── frontend/app/page.tsx      # Minimal black&white dashboard (New/Queue/History/Log/Contacts)
├── docs/{architecture,decisions}.md
├── tests/{test_enquiries,test_duplicate_detection,test_actions}.py
├── requirements.txt
├── .env.example               # GEMINI_API_KEYS= (comma-separated, 7 keys)
└── README.md
```

---

## Testing

```bash
pytest -v
# or: pytest tests/test_duplicate_detection.py -v
```

Covers: invalid input rejected (422), AI output validation, exact duplicate detection, pending-not-executed until approve, rejected never executes, cache hit, fast-path. Mock mode via `GEMINI_API_KEYS=""` (`conftest.py`); live path exercised with 7 keys rotation. `18 passed`.

---

## Environment

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./inboxops.db` | PostgreSQL: `postgresql+psycopg2://user:pass@host:5432/db` |
| `GEMINI_API_KEYS` | _(empty → mock)_ | Comma-separated 7 keys `AQ.Ab8...` (140 RPD). Old `GEMINI_API_KEY` single removed, deduped |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Latest stable |
| `CONFIDENCE_THRESHOLD` | `0.85` | Low-confidence flag |
| `MAX_RETRIES` | `2` | Was 3, now 2 + quota/rate split |
| `MAX_INPUT_LENGTH` | `2000` | Was 8000, now 2000 (~500 tokens) |
| `MAX_OUTPUT_TOKENS` | `800` | Was 350 (truncated), now 800 |
| `RATE_LIMIT_RPM` | `5` | Per key 12s throttle |
| `RATE_LIMIT_RPD` | `20` | Per key per day, 7 keys =140 |
| `CACHE_TTL_SECONDS` | `86400` | 24h hash cache |
| `FRONTEND_URL` | `http://localhost:3000` | CORS |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → API |

---

## License & Notes

Assessment prototype — not a full CRM. Demonstrates **LLM vs deterministic separation** visibly in code, API design, and minimal UI. Audit logs, human approval, and no auto-send are the core safety demonstration. Updated for multi-key rotation, prompt diet, cache & rate limiter to fix `11 RPD/6 RPM → 1-2 RPD` and `Unterminated string col 80` (now fallback to mock, `MAX_OUTPUT_TOKENS 800`).
