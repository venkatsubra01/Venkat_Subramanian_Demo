# Venkat_Subramanian_Demo — local internal-tools prototype

A small, local-only internal tool with two workflows built on shared code:

1. **KYC review** — onboarding cases awaiting a human review of identity-check results.
2. **Refund exceptions** — failed refunds that operations must investigate, created by an inbound demo event.

Stack: React + TypeScript + Vite (frontend), Python FastAPI + Pydantic (API), SQLite + synchronous SQLAlchemy (persistence).
All data is fictional. Nothing here moves money, sends messages, or is deployed. This is **not** production software.

See `docs/build-notes.md` for what was actually run and measured, and `docs/adding-a-tool.md` for the recipe to add another tool.

## Prerequisites

- Python 3.10+ (tested with 3.10.12)
- Node.js 20.19+ or 22.12+ (tested with 24.19.0, npm 10.8.3)

## Install

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # exact pins of everything: requirements.lock
cp .env.example .env
# set SESSION_SECRET in backend/.env, e.g.:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Frontend
cd ../frontend
npm ci
```

## Seed / reset

```bash
cd backend
.venv/bin/python -m app.seed           # seed an empty database (refuses if data already exists)
.venv/bin/python -m app.seed --reset   # drop all tables, recreate, and reseed (destroys local changes)
```

The database lives at `backend/data/app.db` (override with `DATABASE_URL`). The API creates missing tables on
startup but **never reseeds automatically**, so decisions survive page refreshes and backend restarts.

## Run (two terminals)

```bash
# Terminal 1 — API on loopback only
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — UI on loopback; Vite proxies /api to 127.0.0.1:8000
cd frontend
npm run dev
```

Open http://127.0.0.1:5173 and pick an identity from **"Demo identity — no real login"**:

| Identity | Can read records & history | Can make decisions / simulate events |
| --- | --- | --- |
| Vera Viewer (`viewer`) | yes | no (API returns 403) |
| Riley Reviewer (`reviewer`) | yes | yes |

## Test

```bash
cd backend && .venv/bin/python -m pytest -q        # backend checks
cd frontend && npm run typecheck && npm run build  # frontend type/build check
```

## Workflow rules (demo assumptions, not a compliance policy)

**KYC:** `pending_review` → `approved` | `rejected` | `awaiting_information`; `awaiting_information` → `pending_review`.
`approved` and `rejected` are terminal. Reject, request information and return-to-review need a non-blank note; approve's
note is optional.

**Refunds:** `open` → `escalated` | `resolved`; `escalated` → `resolved`. Every action needs a note. `resolved` is terminal.
Resolving records a decision and writes a *local simulated notification* line in activity; it never retries or issues
a payment and nothing is delivered anywhere.

Errors: 401 no/invalid session · 403 viewer mutation or cross-origin mutation · 404 missing record ·
409 disallowed transition or reused event id with different fields · 422 validation failure (e.g. missing note).

## API

| Method & path | Who |
| --- | --- |
| `GET /api/demo/identities` | anyone |
| `GET/POST/DELETE /api/demo/session` | anyone (POST body `{"identity": "viewer" \| "reviewer"}`) |
| `GET /api/kyc?search=&status=&risk=&limit=` | viewer, reviewer |
| `GET /api/kyc/{id}` | viewer, reviewer |
| `POST /api/kyc/{id}/decision` `{"action", "note"}` | reviewer |
| `GET /api/refunds?status=&limit=` | viewer, reviewer |
| `GET /api/refunds/{id}` | viewer, reviewer |
| `POST /api/refunds/{id}/decision` `{"action", "note"}` | reviewer |
| `POST /api/demo/events/refund-failed` | reviewer |
| `GET /api/activity?record_type=&record_id=&limit=` | viewer, reviewer |

### Sample inbound event (demo endpoint, not a payment-provider webhook)

```bash
B=http://127.0.0.1:5173
curl -s -c /tmp/demo.cookies -H "Origin: $B" -H 'Content-Type: application/json' \
  -d '{"identity":"reviewer"}' $B/api/demo/session

curl -s -b /tmp/demo.cookies -H "Origin: $B" -H 'Content-Type: application/json' \
  -d '{"event_id":"evt_demo_readme","payment_reference":"pay_demo_9","amount_minor":1250,"currency":"EUR","failure_reason":"Bank rejected refund"}' \
  $B/api/demo/events/refund-failed
# first call: 201 {"created": true, ...}; identical replay: 200 {"created": false, same id};
# same event_id with different fields: 409
```

`amount_minor` is an integer in minor units (1250 EUR = €12.50). `event_id` is unique in the database
(`refund_exceptions.external_event_id UNIQUE`).

## Layout

```
backend/app/
  config.py    env loading (.env), DB URL, signing secret, allowed origins
  db.py        engine, session, Base, UTC timestamp helper            (shared)
  auth.py      demo identities, signed cookie, viewer/reviewer deps   (shared)
  activity.py  Activity model, record_activity(), GET /api/activity   (shared)
  kyc.py       KYC model, schemas, transitions, routes
  refunds.py   refund model, schemas, transitions, routes, demo event endpoint
  seed.py      fictional seed data / reset
  main.py      app, cross-origin mutation guard, routers
frontend/src/
  components/  DataTable, DetailPanel, DecisionForm, ActivityList, StatusBadge, IdentitySwitcher (shared)
  useApi.ts    small GET-loading hook (shared)
  kyc/         KYC columns, filters, page
  refunds/     refund columns, filters, page, simulate-event form
```

## Security model and known gaps

- The identity switcher proves **authorization**, not authentication: anyone using the local demo can pick either identity.
  The cookie is signed (itsdangerous, `SESSION_SECRET` from `backend/.env`), HttpOnly, SameSite=Strict, and only references
  a fixed server-side identity. Roles in request bodies are ignored.
- Mutations with a non-allowed `Origin` (or `Sec-Fetch-Site: cross-site`) are rejected with 403.
- **Concurrent review protection is a documented gap**: two reviewers acting on the same record at once are not
  detected (last write wins on status; both activity rows are written).
- Activity history is an ordinary table — not tamper-proof.
- No SSO, provisioning, policy admin, monitoring, backups, notification delivery, or payment-provider verification.
