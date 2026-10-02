# Venkat_Subramanian_Demo — local internal-tools prototype

A small, local-only internal tool with three workflows built on shared code:

1. **KYC review** — onboarding cases awaiting a human review of identity-check results.
2. **Refund exceptions** — failed refunds that operations must investigate, created by an inbound demo event.
3. **Chargebacks** — an evidence workspace for card disputes that reuses payment, KYC customer and refund data.

Shared sections across all three: **Work List / My Work** (one review task per actionable case, assignment, priority,
deadlines), an **Approvals** inbox (chargeback evidence approval by a different supervisor) and a supervisor **Audit Log**
built on the existing activity table.

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

The database lives at `backend/data/app.db` (override with `DATABASE_URL`). On startup the API runs the
non-destructive upgrade below but **never reseeds automatically**, so decisions survive page refreshes and backend restarts. Chargeback
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

### Upgrading a database created before the Work Manager

```bash
cd backend
cp data/app.db data/app.db.bak             # optional backup
.venv/bin/python -m app.migrations         # idempotent; prints what it changed, or "Database already up to date."
```

This creates the `work_tasks` and `approval_requests` tables, adds the new `activity` audit columns (existing rows get
`category='case'`, no request id) and `chargebacks.evidence_version` (existing cases start at v1) with
`ALTER TABLE ... ADD COLUMN`, then creates one active task per actionable case (logged as `task_created` by the system
identity). Nothing is dropped, reset or reseeded. Starting the API runs the same step. Upgraded databases have tasks but
no assignments or deadlines; the seeded demo assignments only exist after `app.seed --reset`.

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

**Chargeback evidence approval:** the checklist, notes and attachments are a versioned evidence package
(`evidence_version`). From `ready_for_review` a case actor requests approval of the current version; the request stores
a snapshot (checklist, notes, attachment names/types/sizes/SHA-256 — never file contents). A **different** supervisor
approves (case → `ready_for_submission`) or returns it with a required explanation. Any evidence change bumps the
version, invalidates pending or approved requests and moves `ready_for_submission` back to `ready_for_review`; approving
a request whose version is not current is refused (409). `ready_for_submission` is internal: nothing is sent anywhere.
Close is allowed from `ready_for_review` and `ready_for_submission`; closing invalidates any open request.

**Work tasks:** each case that is not terminal (KYC `pending_review`/`awaiting_information`, refund `open`/`escalated`,
chargeback anything but `closed`) has exactly one active review task (unique on app + record id). The task holds only
assignee, priority, deadline and timestamps; case status stays in the app. Case handlers call `sync_task()` in the same
transaction, so a terminal decision completes the task and a return to an actionable status reactivates the same task.
There is no "complete task" action. A task is overdue when it is active and its deadline (stored in UTC) has passed;
deadlines are demo operational targets. Chargeback tasks default to the evidence deadline.

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
| `GET /api/activity?record_type=&record_id=&category=&limit=` (per-case history; `category` repeatable, default `case`) | any session |
| `POST /api/chargebacks/{id}/approval-requests` | case actor (reviewer, Sky) |
| `POST /api/chargebacks/{id}/approval-requests/{approval_id}/approve` `{"evidence_version"}` | supervisor, not the requester |
| `POST /api/chargebacks/{id}/approval-requests/{approval_id}/return` `{"evidence_version", "reason"}` | supervisor, not the requester |
| `GET /api/work/tasks?app=&assignee_id=&priority=&unassigned=&overdue=&state=` | supervisor |
| `PATCH /api/work/tasks/{id}` `{"assignee_id", "priority", "due_at", "reason"}` (only fields sent are changed) | supervisor |
| `POST /api/work/sync` (idempotent repair from case statuses) | supervisor |
| `GET /api/work/mine?state=` | any session (own assignments) |
| `GET /api/work/by-source/{app}/{id}`, `GET /api/work/assignees` | any session |
| `GET /api/approvals?state=` | supervisor |
| `GET /api/audit?app=&record_id=&actor_id=&action=&category=&request_id=&task_id=&approval_id=&page=&page_size=` | supervisor |

There are no update or delete routes for activity/audit entries.

### Demo identities and permissions

| Identity | Read cases | Change cases / evidence | Be assigned work | Work List, Approvals, Audit Log | Decide approvals |
| --- | --- | --- | --- | --- | --- |
| Vera Viewer (`viewer`) | yes | no | no | no | no |
| Riley Reviewer (`reviewer`) | yes | yes | yes | no | no |
| Sam Second (`reviewer2`) | yes | yes | yes | no | no |
| Sky Supervisor (`supervisor`) | yes | yes | yes | yes | yes, except requests Sky made |
| Pat Approver (`supervisor2`) | yes | no | no | yes | yes, except requests Pat made |
| System (automated, cannot sign in) | — | task sync, approval invalidation | — | — | — |

Assignment never grants access: case routes check the identity's own permissions, and only identities that can change
cases are eligible assignees. Sky holds both roles on purpose, to show that self-approval is still refused.

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
  activity.py  Activity/audit model, record_activity(), request ids, append-only guard, /api/activity, /api/audit (shared)
  tasks.py     WorkTask model, sync_task() — one task per actionable case            (shared)
  approvals.py ApprovalRequest model, create/decide/invalidate helpers, self/stale checks (shared)
  work.py      Work List / My Work / task update routes, approval inbox route
  migrations.py non-destructive upgrade (python -m app.migrations)
  kyc.py       KYC model, schemas, transitions, routes
  refunds.py   refund model, schemas, transitions, routes, demo event endpoint
  payments.py  fictional payment reference data linking payment refs to KYC customers (read-only)
  chargebacks.py dispute, checklist and attachment models; transitions; linked-record lookup; uploads; PDF route
  pdf.py       minimal text-only PDF writer (no third-party dependency)
  seed.py      fictional seed data / reset
  main.py      app, cross-origin mutation guard, routers
frontend/src/
  components/  DataTable, DetailPanel, DecisionForm, ActivityList, StatusBadge, IdentitySwitcher (shared)
  components/CaseTask.tsx  task summary shown in each app's detail panel
  useApi.ts    small GET-loading hook with optional polling (shared)
  work/        Work List (supervisor) and My Work (employee)
  approvals/   approval inbox, evidence snapshot view
  audit/       supervisor Audit Log with filters and pagination
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

## Work Manager, approvals and audit walkthrough (about 4 minutes)

Use two browser windows (e.g. one normal, one private) so two identities are signed in at once.

1. `cd backend && .venv/bin/python -m app.seed --reset`, start both servers, open http://127.0.0.1:5173/#work.
2. **Window A as Sky Supervisor → Work List.** 15 active tasks across the three apps; RFX-SEED0002 is overdue. Try the
   app, assignee, priority, Unassigned and Overdue filters. Select CBK-2003 (unassigned, ready for review), assign it to
   **Riley Reviewer**, set priority high and a deadline, add a reason, Save.
3. **Window B as Riley Reviewer → My Work.** CBK-2003 appears within ~10 s without reloading (polling). Click it to open
   the chargeback.
4. **Prepare evidence (B).** Tick a checklist item or edit the notes: the *Evidence approval* section shows the new
   version (v2, v3…). Click **Request approval of vN**.
5. **Window A → switch to Pat Approver → Approvals.** Open the request: it shows the submitted snapshot (checklist,
   notes, attachment inventory). Approve; the case becomes **ready for submission** (internal only) and its task stays
   active. (As Sky, request approval yourself and try to approve: refused, "You cannot decide on an approval you
   requested.")
6. **Invalidate (B).** Change any evidence item. The approval shows *invalidated* with the reason, the case returns to
   ready for review, and approving the old request from the inbox is refused with 409.
7. **Audit (A as Pat or Sky) → Audit Log.** Filter Record ID `CBK-2003`: task assignment/priority/deadline changes with
   before/after values, evidence edits with version bumps, the approval request/decision/invalidation with approval id,
   and system entries. Click a request id to see every entry written by that one request. Choose category
   *Sensitive views/downloads* to see record views, attachment downloads and PDF exports. Per-case history in each app
   shows case and work events.
8. Close CBK-2003 (Riley): its task completes and leaves My Work.

### What the Work Manager extension reused and added

- Reused unchanged: `db.py` session/engine/UTC helpers, the signed demo session and cross-origin guard, `DataTable`,
  `DetailPanel`/`PanelSection`, `StatusBadge`, `api()`, the hash router, existing case handlers' transaction pattern.
- Extended: `auth.py` (new identities, `can_supervise`, `Supervisor` dependency), `activity.py` (audit columns, request
  ids, append-only guard, sensitive-view helper, `/api/audit`), `useApi` (optional polling), `ActivityList` (before/after,
  task/approval references), each case handler (one `sync_*_task()` call; views/downloads/exports logged), chargebacks
  (evidence version, approval routes, `ready_for_submission`).
- New: `tasks.py`, `approvals.py`, `work.py`, `migrations.py`, `frontend/src/{work,approvals,audit}/`,
  `CaseTask`, `EvidenceApproval`, five backend test files' worth of checks (see build notes).

### Work Manager limitations

- The audit log is **application-level append-only**: no API edits or deletes, and the ORM refuses updates/deletes of
  activity rows. Anyone with access to the SQLite file can still change it; there is no hashing, signing or external copy.
- Record views are logged at most once per identity/record per 10 minutes; list views are not logged.
- Polling (10 s) rather than push; no notification when work is assigned or a deadline passes.
- No concurrency protection: two supervisors editing a task, or an approval racing an evidence edit in separate requests,
  are last-write-wins at the row level (the stale-version check runs inside the approving request's transaction).
- Only chargebacks have approvals. KYC and refund decisions are unchanged and need no approval.
- Task priority for seeded/synced tasks is a simple default; there is no SLA engine or business calendar.
- Demo identities are fixed in code; there is no user administration or team structure.

## Security model and known gaps

- The identity switcher proves **authorization**, not authentication: anyone using the local demo can pick either identity.
  The cookie is signed (itsdangerous, `SESSION_SECRET` from `backend/.env`), HttpOnly, SameSite=Strict, and only references
  a fixed server-side identity. Roles in request bodies are ignored.
- Mutations with a non-allowed `Origin` (or `Sec-Fetch-Site: cross-site`) are rejected with 403.
- **Concurrent review protection is a documented gap**: two reviewers acting on the same record at once are not
  detected (last write wins on status; both activity rows are written).
- Activity history is application-level append-only (see Work Manager limitations) — not tamper-proof.
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
