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

**Data flow (14 steps, sync MVP):** `1 validate → 2 save raw PENDING → 3 audit RECEIVED/STARTED → 4 cache hash 24h (0 calls) → 5 throttle 60/RATE_LIMIT_RPM → 6 Gemini LLM 100% JSON (classification/confidence/contact/company/intent/keywords/priority/missing/action/draft + source context) → 7 Pydantic validate + 3×1s/2s/4s retry/rotate/fallback mock → 8 enrich routing TF-IDF cosine vs 9 real teams threshold 0.12→triage → 9 store AI output → 10 confidence<0.85 flag → 11 duplicate → 12 create PENDING_APPROVAL + NOTIFICATION_QUEUED → 13 return → 14 human approve/reject → deterministic CRM → delete supported for insights/customers`.

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
| `MAX_OUTPUT_TOKENS` | `1200` | Max output tokens for LLM response |
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
