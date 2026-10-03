# Venkat_Subramanian_Demo — local internal-tools prototype

A local-only internal toolset with three workflows built on shared code:

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
