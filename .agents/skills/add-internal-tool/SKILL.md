---
name: add-internal-tool
description: Add a new workflow (queue + detail + decisions + activity) to this repo's local internal-tools app by following docs/adding-a-tool.md. Use when asked to build another internal tool, queue, or review workflow here.
---

# Add an internal tool

1. Read `docs/adding-a-tool.md` and skim `backend/app/refunds.py` + `frontend/src/refunds/` as the reference implementation.
2. Translate the plain-language request into:
   - **Screens**: queue columns, filters, detail fields, actions shown.
   - **Data**: table name, fields and types (money = integer minor units + currency), uniqueness constraints, fictional seed rows.
   - **Rules**: statuses, transition table, note requirements, terminal statuses, who can read vs act, inbound events/idempotency.
3. List every unresolved business decision. **Permission rules and anything touching money or customer outcomes must be
   decided by an engineer or process owner — ask before implementing them.** Do not guess policy.
4. Propose a short implementation plan (files to add/change, tests to write) and wait for authorization if anything in
   step 3 is open.
5. Implement only the authorized scope, reusing `db.py`, `auth.py`, `activity.py`, `DataTable`, `DetailPanel`,
   `DecisionForm`, `ActivityList`, `useApi`. No resource registry, generic action engine, schema-driven forms,
   event bus, or notification outbox.
6. Run and report the actual results of:
   `cd backend && .venv/bin/python -m pytest -q` and `cd frontend && npm run typecheck && npm run build`,
   then a browser pass as both demo identities.

This skill guides the agent; the backend code (`Reviewer`/`CurrentUser` dependencies, transition tables, DB constraints)
is what enforces access and rules.
