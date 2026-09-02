# InboxOps AI — Intelligent Email Enquiry Processing with Human-in-the-Loop Controls

**BEDA AI Systems Assessment — Working Prototype**

> **AI can reason and recommend, but consequential actions must remain under deterministic control and require human approval when appropriate.**

A small, robust prototype that ingests business enquiries (email / website form / chat message), classifies them **LLM 100% with Gemini 3.6 Flash**, extracts structured information, detects duplicates deterministically, **routes to real-world teams via embedding (no manual keyword lists)**, proposes an action, and enforces **human approval before any CRM mutation** — with full auditability, insights dashboard, and cost control. Frontend is **minimal black & white, English, friendly for everyday users (no underscores)**.

---

## Problem

Small businesses receive unstructured enquiries across email, web forms, and messaging. Manually triaging is slow and error-prone; fully autonomous AI risks hallucinations, duplicate CRM records, and irreversible actions (creating contacts, sending externally binding emails).

**This prototype solves:**
- Automatic understanding & extraction without hallucination (`null` when unknown)
- LLM-generated key topics + priority, team routed via TF-IDF embedding (scalable, no hard-coded lists)
- Source-aware routing (email formal / website lead / chat urgent as embedding feature)
- Deterministic duplicate detection (no LLM merging)
- Confidence-gated human review
- Draft responses that are *never auto-sent*
- Insight dashboard that stays viewable after approval
- Audit trail for every event

Focus: **correct controls over autonomous behavior** — not more features, not Kafka/K8s/mega infra.

---

## BEDA Assessment — Direct Answers (8 Required Points)

> Single section that maps 1:1 to spec §25 — evaluator can grade without hunting through the file. Details remain in sections below.

### 1. Simple Architecture — Main Components & Data Flow

```mermaid
flowchart TD
    A[Email / Website / Chat] --> B[FastAPI POST /api/v1/enquiries]
    B --> C[Validation + Normalize 2000 chars]
    C --> D[(PostgreSQL via SQLAlchemy - SQLite dev)]
    C --> E[Gemini 3.6 Flash LLM 100%]
    E --> F[Pydantic Validation extra=forbid]
    F --> G[TF-IDF Routing source-aware + TEAM_DESCRIPTIONS]
    G --> H[Duplicate Detection exact email/phone, possible name+company]
    H --> I[Proposed Action PENDING_APPROVAL + LLM draft]
    I --> J{Human Approval}
    J -->|Approve| K[Deterministic Executor → CRM]
    J -->|Reject| L[Rejected never executes]
    K & L --> M[Audit Log]
    M --> N[Insights Dashboard]
```

**Data flow (14 steps, sync MVP):** `1 validate → 2 save raw PENDING → 3 audit RECEIVED/STARTED → 4 cache hash 24h (0 calls) → 5 throttle 60/RATE_LIMIT_RPM → 6 Gemini LLM 100% JSON (classification/confidence/contact/company/intent/keywords/priority/missing/action/draft + source context) → 7 Pydantic validate + 3×1s/2s/4s retry/rotate/fallback mock → 8 enrich routing TF-IDF cosine vs 9 real teams threshold 0.12→triage → 9 store AI output → 10 confidence<0.85 flag → 11 duplicate → 12 create PENDING_APPROVAL + NOTIFICATION_QUEUED → 13 return → 14 human approve/reject → deterministic CRM → delete supported for insights/customers` — full trace in `## Data Flow`.

### 2. Model & Tool Choices and Why

| Choice | Why |
|---|---|
| **Gemini 3.6 Flash** via `app/services/ai_service.py` | Latest stable (`404 use 3.6-flash`), small/efficient/cheap, low latency. Prompt 400 tokens + `MAX_INPUT 2000` + `MAX_OUTPUT 1200` controls cost. LLM 100% scalable: generates `intent_keywords[3-6 verbatim]` + `priority` + `draft_response` (varied per `SYSTEM_PROMPT:21`) — hard-coded lists don't scale. Mock fallback keeps tests green. |
| **Multi-key rotation** `GEMINI_API_KEYS` comma-separated | On 429 mark key exhausted 24h, rotate (`ai_service.py:352`). Abstracted interface → swap provider without business logic change. |
| **PostgreSQL via SQLAlchemy** (`app/models/database.py`) | Spec-required, ACID, JSON columns for `metadata/ai_output`, indexes on `email/phone`. SQLite default for zero-setup local/tests, same models. |
| **FastAPI + Pydantic + SQLAlchemy** | Auto OpenAPI `/docs`, strict schemas for inputs *and* AI outputs (`extra="forbid"`), typed ORM. |
| **TF-IDF embedding routing** `routing_service.py:86` | LLM keywords+intent+classification+source → cosine vs `TEAM_DESCRIPTIONS` (9 real-world teams). Add team = add one description row, no code change. Source is embedding feature (Opsi A), not `if source==` branch. HR desc now includes `opportunities openings` to fix Daniel Morgan job case. |
| **Next.js 14 minimal B&W** | Spec says `/docs` suffices; we provide layperson dashboard (New/Queue/Insights/History/Log/Customers) white bg black text, no underscores (`Customer Need` not `intent`). |

### 3. What Uses LLM/Agent vs Deterministic Code

| LLM (Gemini 3.6 Flash) | Deterministic Code |
|---|:---:|
| Understand unstructured text, classify `sales/support/junk/needs more info/other` (100%), extract `contact/company/intent/keywords/priority/missing`, recommend action, generate varied `draft_response` (HR-aware, not budget for career) | Validate inputs & AI outputs, confidence gate `<0.85`, duplicate detection, TF-IDF routing, CRM writes, approval enforcement, retries/cache/throttler, audit, secrets, insights aggregation |
| See `## LLM vs Deterministic Code` table for full matrix. | |

**Principle:** LLM recommends, deterministic controls, human approves.

### 4. How We Handle Incomplete / Hallucination / Duplicates / Model Failure

- **Incomplete** (`"Hi, I'm interested"`): LLM → `insufficient_information` + `missing_information: ["company","business_need","contact_details"]` → `REQUEST_MORE_INFORMATION` + varied draft `Hi Alex, could you tell us about your company...` → `PENDING_APPROVAL`, never auto-sent.
- **Hallucination:** Prompt `return null if unknown, never invent` + Pydantic `extra="forbid"` + null enforcement + `intent_keywords` verbatim check. `GEMINI_API_KEYS=""` mock also `null` when unknown.
- **Duplicate:** Deterministic `exact_match` on normalized `email/phone` → `Update Customer`; `possible_duplicate` via `name+company` similarity → human review before merge; LLM cannot merge. Tested `test_duplicate_detection.py`.
- **Model/API failure:** 3× exponential backoff `1s/2s/4s` per spec. `Unterminated string` → regex `\{.*\}` extract + fix → mock fallback (returns `201` mock, not `500`). `429` → mark exhausted 24h + rotate next key. After 3 retries mock fails → `FAILED` only then; original enquiry retained + `AI_ANALYSIS_FAILED` audit. Varied `_mock_draft` now prevents monotonous `Thanks for reaching out, Nadia...`.

### 5. Permissions, Secrets, Sensitive Data

- **Secrets:** `.env` / env vars only (`GEMINI_API_KEYS`, `GEMINI_MODEL`, `DATABASE_URL`, `TEAM_OWNERS`); `.env.example` placeholder; never hard-coded, never in responses/logs. `audit_service.py:34` redacts `key|secret|password|token|api → ***REDACTED***`. Tests force `GEMINI_API_KEYS=""` mock.
- **Permissions:** `action_service.approve` checks `PENDING_APPROVAL` only; placeholder `demo_user` with comment production uses RBAC/OAuth; least privilege — AI cannot access secrets, delete/merge, send, or tool-use (routing is embedding, not tool). `DELETE /enquiries` + `DELETE /crm/contacts` also `human:demo_user`.
- **Sensitive data:** `sender_email/phone` normalized but not exposed beyond need; `audit.metadata` sanitized; chat without email uses placeholder `chatuser@chat.local` hidden as `via Chat` in UI. CORS limited to `FRONTEND_URL`/`CORS_ORIGINS`.

### 6. Cost & Latency Under Control

- **Cache** `hash(email|source|message)` 24h TTL max 500 → 0 calls on repeat demos
- **Throttler** `60/RATE_LIMIT_RPM` per key before LLM call
- **Rotation** on rate-limit → next key; all exhausted → mock (0 calls)
- **Tokens** prompt 400 + `MAX_INPUT 2000 (~500 tokens)` + `MAX_OUTPUT 1200` → bounded; `truncate_input` caps TPM even if user pastes long email
- **Model** Flash small/cheap; no RAG/vector DB for MVP
- **Latency** sync MVP ~1–2s (throttled if burst); prod path documented `API → Queue → Worker → Async + Notifier (webhook/Slack/email)` in `docs/architecture.md:170`
- HR fix keeps cost same (9 team descs, no extra LLM calls).

### 7. One Thing Deliberately Refused to Automate

> **The system deliberately refuses to autonomously send externally binding communications or perform irreversible CRM changes without human approval.**

Drafts stored inside `proposed_actions.draft_response` never emailed; `CREATE_LEAD/UPDATE_CONTACT/CREATE_SUPPORT_CASE` execute only after `POST /actions/{id}/approve`; `REJECTED` never executes; merge requires human; `NOTIFICATION_QUEUED` only alerts assignee; job enquiry `"Hi BEDA team, Daniel Morgan job opportunities"` correctly routes to HR with `CV` draft, but still `PENDING_APPROVAL` — human must approve.

### 8. Pseudocode — Approval Gate (Important Part, current runnable)

```python
# app/services/enquiry_processor.py:16 + ai_service.py:232 + routing_service.py:111 + action_service.py:58
def process_enquiry(enquiry):
    save_raw(enquiry)  # enquiries PENDING
    audit("ENQUIRY_RECEIVED", source=enquiry.source)

    if cached := cache.get(hash(enquiry)):  # 0 tokens
        analysis = cached
    else:
        throttle(key)  # 60/RATE_LIMIT_RPM
        raw = gemini_3_6_flash(enquiry)  # LLM 100% — source-aware, varied draft
        analysis = AIAnalysis.model_validate(raw)  # extra=forbid, max 6 keywords, priority enum
        analysis.suggested_team = route_team(  # Option B + Opsi A
            query=" ".join(analysis.intent_keywords) + " " + analysis.intent,
            classification=analysis.classification, source=enquiry.source,
        )  # TF-IDF cosine vs TEAM_DESCRIPTIONS (HR now includes opportunities/openings)

    if analysis.confidence < 0.85:
        flag_needs_review()
    duplicate = find_duplicate(email, phone, name, company)  # deterministic
    proposed = create_action(enquiry, analysis, duplicate,
        status="PENDING_APPROVAL", requires_human_approval=True,  # even 0.95
        team=analysis.suggested_team, owner=TEAM_OWNERS[team])
    audit("ACTION_CREATED", team=team, owner=owner)
    audit("NOTIFICATION_QUEUED", assigned_to=owner)
    return proposed

# Human gate — configured via .env:
# GEMINI_API_KEYS=key1,key2  LLM_MODEL=gemini-3.6-flash
# MAX_RETRIES=3 MAX_INPUT_LENGTH=2000 MAX_OUTPUT_TOKENS=1200
# RATE_LIMIT_RPM=5 RATE_LIMIT_RPD=20 CACHE_TTL_SECONDS=86400
# TEAM_DESCRIPTIONS: 9 teams (hr includes "opportunities openings")
# POST /actions/{id}/approve → check PENDING → deterministic execute → AUDIT EXECUTED
# POST /actions/{id}/reject  → REJECTED (never executes)
# DELETE /enquiries/{id} / DELETE /crm/contacts/{id} → human + audit
```

---

## Quick Start

### Backend (FastAPI)

```bash
# 1. Clone & env
cp .env.example .env
# edit .env: set GEMINI_API_KEYS as comma-separated and GEMINI_MODEL=gemini-3.6-flash
# Example: GEMINI_API_KEYS=AQ.Ab8...,AQ.Ab8...
# Get keys from https://aistudio.google.com/app/apikey
# DATABASE_URL defaults to sqlite:///./inboxops.db (use PostgreSQL in prod: postgresql+psycopg2://user:pass@host:5432/inboxops)

# 2. Install & run
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# -> http://localhost:8000/docs  (Swagger)
# -> http://localhost:8000/health  (shows mock_mode, keys count)
```

Without `GEMINI_API_KEYS`, the service runs in **deterministic mock mode** (heuristics, no API cost) — tests remain green offline (`tests/conftest.py` forces mock via `GEMINI_API_KEYS=""`).

### Frontend (Next.js — Minimal Black & White, layperson)

```bash
cd frontend
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                  # http://localhost:3000  — minimal UI: white bg, black text, no underscores
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
    A[Email / Website Form / Chat Message] --> B[FastAPI Ingestion API]
    B --> C[Validation & Normalization 2000 chars]
    C --> D[(PostgreSQL via SQLAlchemy)]
    C --> E[AI Analysis Service - Gemini 3.6 Flash LLM 100%]
    E --> F[Classification & Extraction<br/>intent + key topics + priority]
    F --> G[Pydantic Validation extra=forbid]
    G --> H[Routing Service<br/>TF-IDF embedding source-aware<br/>team vs keywords+intent]
    H --> I[Duplicate Detection<br/>exact email/phone, possible name+company]
    I --> J[Proposed Action<br/>PENDING_APPROVAL + draft]
    J --> K{Human Approval Required?}
    K -->|Yes| L[Pending Approval]
    L --> M[Human Reviewer - Minimal UI]
    M -->|Approve| N[Deterministic Action Executor]
    M -->|Reject| O[Rejected]
    N --> P[CRM Database Update]
    O --> Q[Audit Log]
    P --> Q
    P --> R[Insights Aggregator]
    E --> Q
    H --> Q
    I --> Q
```

**Detailed:** [`docs/architecture.md`](docs/architecture.md) • **Decisions:** [`docs/decisions.md`](docs/decisions.md)

---

## Data Flow

```
POST /api/v1/enquiries {source, sender_name, sender_email, message}
  │
  ├─ 1. Pydantic validate + normalize (strip, lowercase email, 2000 char limit)
  ├─ 2. Save raw enquiry (enquiries table, processing_status=PENDING)
  ├─ 3. Audit ENQUIRY_RECEIVED + AI_ANALYSIS_STARTED
  ├─ 4. Cache hit? → hash(email|source|message) 24h TTL → return cached (0 tokens/calls)
  ├─ 5. Rate throttler → waits 60/RATE_LIMIT_RPM per key before LLM call
  ├─ 6. Gemini 3.6 Flash — LLM 100% determines classification (prompt includes source context: email formal / website lead / chat urgent)
  │     Returns strict JSON: classification, confidence, contact, company, intent, intent_keywords[3-6], priority, missing_information, recommended_action, draft_response
  ├─ 7. Pydantic validate AI output (extra="forbid", confidence 0.0-1.0, priority enum, max 6 keywords); on invalid JSON/rate limit: retry 3× exponential backoff (1s/2s/4s) with key rotation
  │     • Rate limit → mark key exhausted 24h and rotate, fallback to mock if all exhausted
  │     • Invalid JSON → extract {.*} fallback, then fallback to mock
  ├─ 8. On failure after retries → fallback to mock (not FAILED) + AI_ANALYSIS_COMPLETED(mock); if mock fails → FAILED
  ├─ 9. Enrich routing: keywords+intent+classification+source → TF-IDF cosine vs TEAM_DESCRIPTIONS (9 real-world teams) → suggested_team + assigned_owner (threshold 0.12 → triage)
  ├─10. On success: store ai_classification/confidence/ai_output (with keywords/priority/team); AI_ANALYSIS_COMPLETED
  ├─11. Confidence < 0.85? → flag low_confidence in metadata (still PENDING_APPROVAL)
  ├─12. Duplicate detection (exact phone/email → exact_match; name+company → possible_duplicate)
  ├─13. Create proposed_actions (status=PENDING_APPROVAL, requires_human_approval=true, metadata includes team/owner/keywords/priority) + ACTION_CREATED + DUPLICATE_DETECTED + NOTIFICATION_QUEUED (alert right person, not auto-send)
  └─14. Return {enquiry, proposed_action, duplicate_status}
        → UI shows Smart Analysis: Customer Need, Key Topics, Responsible Team, Person in Charge, Priority Level, Still Needs, Suggested Reply
        → Human: POST /api/v1/actions/{id}/approve|reject
             • approve: check PENDING, log ACTION_APPROVED, deterministic execute (create company/contact etc), log ACTION_EXECUTED, status=EXECUTED
             • reject: status=REJECTED, ACTION_REJECTED, never executes
        → Insight stays viewable: GET /api/v1/insights/enquiry/{id} and Insights tab (summary + recent)
```

**Sync for MVP** — production could be `API → Queue → Worker → Async`. Source is not an `if source==` branch; it is an **embedding feature** that biases routing via TF-IDF (Opsi A).

---

## Model and Tool Choices

**Why LLM (Gemini 3.6 Flash) — LLM 100% scalable?**
- Understands unstructured free-text, classifies intent, extracts entities, **generates key topics (3-6 verbatim) + priority (low/medium/high)** — tasks where hard-coded keyword lists fail to scale. Add a team = add one description in `TEAM_DESCRIPTIONS`, no code change.
- 3.6 Flash = latest stable (API confirms 2.0/1.5 no longer available `404 use 3.6-flash`), small/efficient, low latency, cheap; prompt instructs `null` when unknown to avoid hallucination and respects `source` context.
- **LLM 100% classification** (`LLM_ONLY_CLASSIFICATION=True`): no manual `SPAM_KEYWORDS` gate for routing. LLM determines `junk/insufficient/support/sales` directly; deterministic only validates enum.
- **Multi-key rotation** via `GEMINI_API_KEYS` comma-separated (`app/core/config.py:67`, `app/services/ai_service.py:352`): on rate limit errors mark key exhausted 24h and rotate with retry. Deduped and configurable.
- Prompt compacted 800→400 tokens (`SYSTEM_PROMPT` `ai_service.py:20`) + `MAX_INPUT 2000` + `MAX_OUTPUT 800` to control input cost; extended with `intent_keywords/priority` and source hint.
- Abstracted via `app/services/ai_service.py` (interface, not coupled); swap provider by replacing service.

**Why deterministic code?**
- Permissions, validation, confidence gate, duplicate detection, TF-IDF routing, CRM writes, approval enforcement, retries, audit, secrets, cache, rate limiter — must be **reproducible, testable, auditable**, not probabilistic.

**Why PostgreSQL (via SQLAlchemy)?**
- Spec requirement; ACID, JSON columns for flexible metadata, indexes for email/phone. SQLite default for zero-setup local/tests — same SQLAlchemy models, no code fork.

**Why human approval?**
- Consequential actions (create contact, send email, merge records) are irreversible/binding. Human retains control; LLM only recommends.

**Why Next.js frontend (minimal, layperson)?**
- Spec: `/docs` suffices; optional minimal UI. We provide **minimal black & white, English, friendly for everyday users** dashboard (New / Queue / Insights / History / Activity Log / Customers) — white bg, black text, no underscores, full words (“Customer Need” not “intent”, “Key Topics” not “intent_keywords”, “Responsible Team” not “suggested_team”, “Billing and Finance” not “billing_finance”).

**Why FastAPI + Pydantic + SQLAlchemy?**
- FastAPI: auto OpenAPI at `/docs`, Pydantic integration, async-ready.
- Pydantic: strict schema for both API inputs and AI outputs.
- SQLAlchemy 2.0: typed Mapped models, pool handling for PG & SQLite.

---

## LLM vs Deterministic Code

| Responsibility | LLM (Gemini 3.6 Flash) | Deterministic Code |
|---|:---:|:---:|
| Understand unstructured enquiry | **Yes** | No |
| Classification (`sales/support/junk/needs more info/other`) | **Yes (100%)** | **Validation only** (no manual keyword gate) |
| Extract information (name/email/phone/company/size + customer need + key topics + priority level) | **Yes** (topics verbatim from message) | **Validation** (Pydantic, null enforcement, max 6 topics) |
| Identify still needs | **Yes** | Flag + surface to human |
| Recommend next step | **Yes** (suggestion) | **Controls** (maps to allowed enum, decides final type) |
| Route to real-world team (`Sales/Support/Billing and Finance/Partnership/Operations/Marketing/Human Resources/Legal/General Support`) | **Yes** (key topics + customer need via TF-IDF embedding Option B) | **Yes** — embedding cosine vs `TEAM_DESCRIPTIONS` (`routing_service.py:45`), threshold 0.12 → General Support; `TEAM_OWNERS` mapping; source augments query (Opsi A) |
| Suggest reply | **Yes** | **Not sent** — stores draft, human approves |
| Send externally binding communication | No | **Human approval required** |
| Duplicate detection | No | **Yes** (exact email/phone, possible name+company) |
| Permission / confidence checks | No | **Yes** (0.85 threshold, needs review flag) |
| Customer records (`contacts`, `companies`) | No | **Yes** (deterministic executor after approve) |
| Merge customer records | No | **No** — blocked; human review required |
| Retry / backoff / failure handling | No | **Yes** (3× 1s/2s/4s + JSON fallback to mock) |
| Cache (24h hash) / Throttler | No | **Yes** (`ai_service.py:92`, throttler uses `RATE_LIMIT_RPM`) |
| Audit + insights | No | **Yes** (stores responsible team / key topics / priority / person in charge) |
| Access secrets | No | **Yes** (least privilege, never in logs) |

---

## Failure Handling

- **Still needs info** (`"Hi, I'm interested"`): LLM returns `needs more info` with `still needs: ["company","business need","contact details"]`, `Ask for More Details`, draft clarification — marked `Waiting for Review`, never auto-sent. Tested in mock + live.
- **Hallucination prevention**: Prompt says “return `null` when not available, never invent”. Pydantic `extra="forbid"` + `null` enforcement + validation retry; source is light context, not override.
- **Duplicate records**: Exact `email`/`phone` normalized → `exact match` → propose `Update Customer`; `name+company` normalized/similarity → `possible duplicate` → human review before merge; LLM cannot merge.
- **Model failure / invalid JSON / timeout / rate limit** (3 retries, exponential backoff 1s/2s/4s per spec): 
  - `Unterminated string` / `Expecting ','` → robust JSON extract `re.search(r"\{.*\}", DOTALL)` + fix, then fallback to mock (not error). Returns `201` mock on fallback.
  - Rate limit → mark key exhausted 24h, rotate to next key, fallback to mock if all exhausted.
  - After 3 retries `processing_status=FAILED` only if mock also fails; else `Done` with mock.
- **Low confidence**: `<0.85` flagged in `low confidence flag`; step still waiting for review.
- **Rejection**: `Rejected` status; executor checks `Waiting for Review` only — rejected never executes (tested).

---

## Security

- **Secrets**: via `GEMINI_API_KEYS` (comma-separated), `GEMINI_MODEL`, `DATABASE_URL`, `TEAM_OWNERS` in `.env` / env vars; `.env.example` placeholder; never hard-coded, never in responses/logs. `audit_service` redacts keys (`***REDACTED***`).
- **Permissions**: `action_service.approve` checks `Waiting for Review`; placeholder `actor_id=demo_user` with comment that production uses RBAC/OAuth; least privilege (AI cannot access secrets, delete, merge, send, or use tools via `routing_service` — team is embedding, not tool).
- **Sensitive data**: Email/phone normalized but not exposed beyond need; audit `metadata` sanitized.
- **Validation**: All inputs via `EnquiryCreateRequest` (valid email, 1-2000 chars, channel enum); AI output via `AIAnalysis` (key topics max 6, priority enum, responsible team validated).
- **CORS**: Limited to `FRONTEND_URL` / `CORS_ORIGINS`.

---

## Cost and Latency

**How this project keeps cost predictable:**
- **Cache**: `hash(email|channel|message)` 24h TTL (`CACHE_TTL_SECONDS 86400`, max 500) → repeated messages cost 0 calls.
- **Throttler**: waits `60 / RATE_LIMIT_RPM` per key before each LLM call.
- **Key rotation**: on rate limit errors mark key exhausted 24h and rotate to next key. When all keys exhausted → mock fallback.
- **Prompt & tokens**: compact prompt (~400 tokens) + `MAX_INPUT 2000` + `MAX_OUTPUT 800` to control token usage.
- **Input caps**: `MAX_INPUT_LENGTH=2000` truncates before LLM.
- **Latency**: Sync MVP (~1–2s incl. LLM, throttled if burst); production path noted as `Message Queue + Worker + Async`.

**Tune for your case:** set `RATE_LIMIT_RPM`/`RPD` and `GEMINI_API_KEYS` via `.env`; keep `MAX_INPUT_LENGTH`/`MAX_OUTPUT_TOKENS` as is unless you need longer drafts.

---

## Deliberately Not Automated

> **The system deliberately refuses to autonomously send externally binding communications or perform irreversible customer changes without appropriate human approval.**

Specifically: drafts are stored, never emailed; `Create New Customer`/`Update Customer`/`Create Support Ticket` execute only after `POST /actions/{id}/approve`; `Rejected` never executes; merging requires human review; even with cache, rate-limit exhausted still falls back to mock, never auto-sends. Source and keyword routing never auto-act — they only suggest.

---

## Pseudocode — Approval Gate (Critical Part, current)

```python
# app/services/enquiry_processor.py:14 + ai_service.py:231 + routing_service.py:45 + action_service.py:58
def process_enquiry(enquiry):
    save_raw(enquiry)  # enquiries Waiting
    audit("Enquiry Received", channel=enquiry.source)

    if cached := cache.get(hash(enquiry)):  # 0 tokens
        analysis = cached
    else:
        throttle(key)  # waits 60 / RATE_LIMIT_RPM
        raw = gemini_3_6_flash(enquiry)  # LLM 100% — includes source context
        analysis = AIAnalysis.model_validate(raw)  # extra=forbid, priority enum, max 6 topics
        analysis.suggested_team = route_team(  # Option B + Opsi A
            query=" ".join(analysis.intent_keywords) + " " + analysis.intent,
            classification=analysis.classification,
            source=enquiry.source,  # email formal / website lead / chat urgent augments embedding
        )

    if analysis.confidence < 0.85:
        flag_needs_review()

    duplicate = find_duplicate(email, phone, name, company)  # deterministic

    proposed = create_action(
        enquiry, analysis, duplicate,
        status="Waiting for Review",
        requires_human_approval=True,  # even if 0.95
        team=analysis.suggested_team, owner=TEAM_OWNERS[team]
    )
    audit("Next Step Created", team=team, owner=owner)
    audit("Notification Queued", assigned_to=owner)  # alert right person, not send to customer
    return proposed

# Human must approve:
# POST /actions/{id}/approve -> check Waiting -> deterministic execute -> audit Done
# POST /actions/{id}/reject  -> Rejected (never executes)
```

---

## Prototype Scope

This repository **intentionally implements the critical control path** rather than building a full customer system or unnecessary infrastructure:

- ✅ Working FastAPI + PostgreSQL (SQLite dev) + AI abstraction (LLM 100%, multi-key rotation, cache, throttler) + Pydantic validation (key topics max 6) + duplicate detection + real-world teams via TF-IDF embedding + source-aware routing + human approval + deterministic executor + insights aggregator + audit logs + tests + architecture docs + minimal Next.js dashboard (New / Queue / Insights / History / Activity Log / Customers, layperson, no underscores)
- ❌ Not built: real email sending, full RBAC, Kafka/K8s/Airflow, microservices, multi-agent, RAG/vector DB — all noted as “scalable path later” per spec.

Clear architecture > more features. Correct controls > autonomous AI.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/enquiries` | Ingest enquiry (validate→AI LLM 100%→routing embedding→duplicate→propose) |
| `GET` | `/api/v1/enquiries?source=&classification=` | List enquiries (filter by channel) |
| `GET` | `/api/v1/enquiries/{id}` | Get enquiry |
| `GET` | `/api/v1/enquiries/{id}/actions` | Actions for enquiry |
| `GET` | `/api/v1/enquiries/{id}/audit` | Audit for enquiry |
| `GET` | `/api/v1/actions?status=Waiting for Review` | List actions (pending queue) |
| `GET` | `/api/v1/actions/{id}` | Get action |
| `POST` | `/api/v1/actions/{id}/approve` | Human approve → execute |
| `POST` | `/api/v1/actions/{id}/reject` | Human reject (never executes) |
| `GET` | `/api/v1/insights/summary` | Aggregated insights: by channel/team/priority/category |
| `GET` | `/api/v1/insights/recent?source=&team=&limit=` | Recent insights (LLM understanding stays viewable after review) |
| `GET` | `/api/v1/insights/enquiry/{id}` | Full insight for one enquiry (message + analysis + actions + audit) |
| `GET` | `/api/v1/teams` | List real-world teams + person in charge + description (add team = add row, no code change) |
| `POST` | `/api/v1/teams/route-preview` | Preview routing scores for `message`/`key topics` (TF-IDF) |
| `GET` | `/api/v1/audit?limit=` | Recent activity |
| `GET` | `/api/v1/crm/contacts` | List customers (simulation) |
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

**Example response:** `category=Sales Opportunity (95%) via Email`, `duplicate check=no duplicate`, `responsible team=Sales → Person in Charge: owner_sales@beda.id`, `key topics=[ai automation, customer support]`, `priority=Medium Priority`, `next step=Create New Customer, Waiting for Review, Suggested Reply: "Thank you..."` — still `201`, never auto-sent. On rate limit error returns `201` with mock fallback (not `500`). Try same message with `source=messaging` → team may shift to Support due to source embedding.

---

## Repository Structure

```
├── app/main.py                # FastAPI, lifespan, CORS, /health
├── app/api/{enquiries,actions,teams,insights}.py
├── app/core/{config,logging}.py  # TEAM_DESCRIPTIONS, TEAM_OWNERS, RATE_LIMIT_* configurable
├── app/models/{database,schemas}.py  # TeamEnum 9 teams, AIAnalysis with key topics/priority/suggested team
├── app/services/{ai_service,routing_service,enquiry_processor,duplicate_detector,action_service,audit_service,notifier}.py
├── frontend/app/page.tsx      # Minimal black & white dashboard (New / Queue / Insights / History / Activity Log / Customers, layperson)
├── frontend/lib/api.ts
├── docs/{architecture,decisions}.md
├── tests/{test_enquiries,test_duplicate_detection,test_actions}.py
├── requirements.txt
├── .env.example               # GEMINI_API_KEYS= (comma-separated)
└── README.md
```

---

## Testing

```bash
pytest -v
# or: pytest tests/test_duplicate_detection.py -v
```

Covers: invalid input rejected (422), AI output validation (extra=forbid, priority enum), exact duplicate detection, waiting-not-executed until approve, rejected never executes, cache hit, source-aware routing. Mock mode via `GEMINI_API_KEYS=""` (`conftest.py`); live path exercised with rotation. `18 passed`.

To test source effect manually: create same message with `source=email` vs `source=messaging` → `GET /api/v1/insights/recent` shows different `responsible team` for same text.

---

## Environment

| Variable | Default (example) | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./inboxops.db` | PostgreSQL: `postgresql+psycopg2://user:pass@host:5432/db` |
| `GEMINI_API_KEYS` | _(empty → mock)_ | Comma-separated keys for rotation |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Latest stable |
| `CONFIDENCE_THRESHOLD` | `0.85` | Needs review flag |
| `MAX_RETRIES` | `3` | Per spec 1s/2s/4s exponential backoff |
| `MAX_INPUT_LENGTH` | `2000` | Truncate before LLM |
| `MAX_OUTPUT_TOKENS` | `800` | Max output tokens for LLM response |
| `RATE_LIMIT_RPM` | `5` | Requests per minute per key → throttler waits `60/RPM` |
| `RATE_LIMIT_RPD` | `20` | Requests per day per key → rotation marks exhausted 24h per key |
| `CACHE_TTL_SECONDS` | `86400` | 24h hash cache (0 calls on hit) |
| `TEAM_OWNERS` / `TEAM_DESCRIPTIONS` | 9 teams | Add team = add row, no code change (real-world) |
| `FRONTEND_URL` | `http://localhost:3000` | CORS |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → API |

---

## Screenshots

![](./screenshot/ScreenShot%20Tool%20-20260902065701.png)
![](./screenshot/ScreenShot%20Tool%20-20260902065758.png)
![](./screenshot/ScreenShot%20Tool%20-20260902065808.png)
![](./screenshot/ScreenShot%20Tool%20-20260902065820.png)
![](./screenshot/ScreenShot%20Tool%20-20260902065834.png)
![](./screenshot/ScreenShot%20Tool%20-20260902065857.png)

---

## License & Notes

Assessment prototype — not a full customer system. Demonstrates **LLM vs deterministic separation** visibly in code, API design, and minimal UI. Audit + human approval + no auto-send are the core safety demonstration. Current: LLM 100% (no hard-coded lists), 9 real-world teams via embedding + source-aware, layperson UI, insights that stay after review, configurable rate limits.
