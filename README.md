# Venkat_Subramanian_Demo — local internal-tools prototype

A small, local-only internal tool with three workflows built on shared code:

1. **KYC review** — onboarding cases awaiting a human review of identity-check results.
2. **Refund exceptions** — failed refunds that operations must investigate, created by an inbound demo event.
3. **Chargebacks** — an evidence workspace for card disputes that reuses payment, KYC customer and refund data.

Stack: React + TypeScript + Vite (frontend), Python FastAPI + Pydantic (API), SQLite + synchronous SQLAlchemy (persistence).
All data is fictional. Nothing here moves money, sends messages, contacts a payment provider, submits disputes, or is deployed. This is **not** production software.

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
.venv/bin/python -m app.seed --reset   # drop all tables, delete stored attachments, recreate, reseed (destroys local changes)
```

The database lives at `backend/data/app.db` (override with `DATABASE_URL`). The API creates missing tables on
startup but **never reseeds automatically**, so decisions survive page refreshes and backend restarts. Chargeback
evidence files are stored under `backend/data/attachments/` (override with `ATTACHMENTS_DIR`); both are git-ignored.
Chargeback evidence deadlines are seeded relative to the time you run the seed, so overdue cases always exist.

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

**Chargebacks:** `open` →(start collecting)→ `collecting_evidence` →(mark ready)→ `ready_for_review` →(close)→ `closed`.
Closing requires an outcome (`won`, `lost`, `accepted`, `withdrawn`); notes are optional. `closed` is terminal and makes
the checklist, notes and attachments read-only. A case is *overdue* when it is not closed and its evidence deadline has
passed. Checklist items per dispute reason and the deadlines are demo assumptions, not card-network rules. Every status
change, checklist toggle, notes save and upload writes an activity row in the same transaction.

**Attachments:** PDF, PNG, JPEG or plain text only, up to 5 MB each and 20 per case. The API checks the declared type,
the file extension and the file's leading bytes, stores files under a server-generated name (the uploaded name is only
display metadata) and serves downloads with `Content-Disposition: attachment` and `nosniff`. Uploading needs the reviewer
identity; downloading needs any valid session. There is no delete in this demo.

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
| `GET /api/chargebacks?status=&overdue=&limit=` | viewer, reviewer |
| `GET /api/chargebacks/{id}` (includes linked payment, KYC customer, refunds, checklist, attachments, missing info) | viewer, reviewer |
| `POST /api/chargebacks/{id}/decision` `{"action", "outcome", "note"}` | reviewer |
| `PUT /api/chargebacks/{id}/checklist/{item_key}` `{"done"}` | reviewer |
| `PUT /api/chargebacks/{id}/notes` `{"notes"}` | reviewer |
| `POST /api/chargebacks/{id}/attachments?filename=` (raw file body, `Content-Type` = file type) | reviewer |
| `GET /api/chargebacks/{id}/attachments/{attachment_id}` | viewer, reviewer |
| `GET /api/chargebacks/{id}/summary.pdf` | viewer, reviewer |
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
  payments.py  fictional payment reference data linking payment refs to KYC customers (read-only)
  chargebacks.py dispute, checklist and attachment models; transitions; linked-record lookup; uploads; PDF route
  pdf.py       minimal text-only PDF writer (no third-party dependency)
  seed.py      fictional seed data / reset
  main.py      app, cross-origin mutation guard, routers
frontend/src/
  components/  DataTable, DetailPanel, DecisionForm, ActivityList, StatusBadge, IdentitySwitcher (shared)
  useApi.ts    small GET-loading hook (shared)
  kyc/         KYC columns, filters, page
  refunds/     refund columns, filters, page, simulate-event form
  chargebacks/ dispute columns, filters, page, decision form with outcome, checklist/notes/attachment sections
```

## Chargeback demo walkthrough (about 3 minutes)

1. `cd backend && .venv/bin/python -m app.seed --reset`, start both servers, open http://127.0.0.1:5173/#chargebacks.
2. As **Vera Viewer**: the queue shows customer, payment reference, disputed amount, reason, deadline and status. CBK-2001
   and CBK-2005 are highlighted as overdue; try the status filter and "Overdue only". Open CBK-2001: checklist, notes,
   upload and workflow controls are read-only, but the PDF and any attachments can be downloaded.
3. In CBK-2001's detail, the **Customer** link opens KYC-1004 on the KYC page and the **Refund history** link opens
   RFX-SEED0001 on the Refunds page (`#kyc/<id>`, `#refunds/<id>`). Open CBK-2005 (payment has no KYC customer) and
   CBK-2006 (payment reference not found) to see missing information called out.
4. Switch to **Riley Reviewer**, open CBK-2002: tick checklist items, save a note, upload a small `.txt`/`.png`/`.pdf`
   (a `.html` or `.exe` is rejected), and download it back. Each change appears in Activity history.
5. Start collecting → Mark ready → Close. Closing without an outcome is refused; choose one and the case becomes read-only.
6. Download the evidence summary PDF. Its header says **NOT A SUBMISSION PACKAGE**: it lists attachments (name, type,
   size, SHA-256) but does not contain them.
7. Refresh the page and restart the API: status, notes, checklist and attachments are still there.

### What the chargeback workspace reused

- Backend: `db.py` (engine, session, `Base`, `UTCDateTime`, `utcnow`), `auth.py` (`CurrentUser` for reads, `Reviewer` for
  writes, cross-origin guard in `main.py`), `activity.py` (`record_activity` in the same transaction, `GET /api/activity`),
  the `RefundException` model and `RefundOut` schema (linked refund history), the `KycCase` model (customer summary).
- Frontend: `DataTable` (gained an optional `rowClassName` prop for overdue rows), `DetailPanel`/`PanelSection`/
  `DetailPanelPlaceholder`, `ActivityList`, `StatusBadge`, `useApi`, `api()` (gained an `uploadFile()` sibling),
  `formatMinorUnits`, `humanize`/`formatTimestamp`. KYC and refund pages gained an optional `initialId` so other
  workflows can deep-link to a record.
- New and chargeback-specific: `payments.py`, `chargebacks.py`, `pdf.py`, `frontend/src/chargebacks/*`, its own decision
  form (`DecisionForm` has no outcome field; adding one there would have made it generic), and a few CSS rules.

### Checks actually run for the chargeback workspace

See `docs/build-notes.md` ("Chargeback evidence workspace") for commands, output and the browser pass.

## Security model and known gaps

- The identity switcher proves **authorization**, not authentication: anyone using the local demo can pick either identity.
  The cookie is signed (itsdangerous, `SESSION_SECRET` from `backend/.env`), HttpOnly, SameSite=Strict, and only references
  a fixed server-side identity. Roles in request bodies are ignored.
- Mutations with a non-allowed `Origin` (or `Sec-Fetch-Site: cross-site`) are rejected with 403.
- **Concurrent review protection is a documented gap**: two reviewers acting on the same record at once are not
  detected (last write wins on status; both activity rows are written).
- Activity history is an ordinary table — not tamper-proof.
- No SSO, provisioning, policy admin, monitoring, backups, notification delivery, or payment-provider verification.

### Chargeback limitations

- Payments are a small seeded reference table, not a ledger or a provider integration; links are by payment reference.
  The seeded cardholder names are shown "as reported" and are not reconciled against the KYC customer name.
- Deadlines, reasons, checklist items and outcomes are demo assumptions. Nothing is submitted to a card network or
  provider, and no reminder is sent when a deadline passes (overdue is only highlighted).
- The PDF is a text-only internal summary (built-in Helvetica, Latin-1/cp1252 only; other characters print as `?`). It
  does not embed attachments and is not a submission package.
- Attachments: no virus scanning, no deletion or versioning, files live on local disk with no encryption or backup;
  content checks are a leading-bytes sniff, not full validation. Upload bodies are held in memory (5 MB cap).
- No concurrency protection on notes or checklist edits (last write wins; each write is still logged).
