# Recipe: adding another internal tool

This is how the refund-exceptions workflow was added on top of KYC. Follow the same steps for a new tool. Do not add
a resource registry, generic action engine, schema-driven forms, event bus, or notification outbox — each tool gets its
own explicit model, schemas and handlers.

## 1. Define the records and decisions (on paper first)

Write down, in plain language:

- **Record fields** and their types (money as integer minor units + ISO currency, timestamps in UTC).
- **Statuses** and the **allowed transitions** as a table: `from_status --action--> to_status`.
- Which actions **require a note**, and which statuses are **terminal**.
- **Who** may read and who may act. Today there are two identities: `viewer` (read) and `reviewer` (read + act).
- Any **inbound integration** (event id uniqueness, replay behaviour).

If a permission or financial rule is unclear (who may approve, amount thresholds, what "resolve" means for money),
stop and get an engineer / process owner to decide. Do not invent policy in code.

## 2. Identify what you reuse

| Need | Reuse | Location |
| --- | --- | --- |
| DB engine/session/Base, UTC timestamps | yes | `backend/app/db.py` |
| Session cookie, `CurrentUser`, `Reviewer` deps | yes | `backend/app/auth.py` |
| Activity rows + history endpoint | yes — call `record_activity()` | `backend/app/activity.py` |
| Queue table | yes — pass `Column<T>[]` | `frontend/src/components/DataTable.tsx` |
| Detail layout | yes — `DetailPanel`, `PanelSection`, `DetailPanelPlaceholder` | `frontend/src/components/DetailPanel.tsx` |
| Action + note form | yes — `DecisionForm` with `allowedActions`, `noteRequired` | `frontend/src/components/DecisionForm.tsx` |
| History list | yes — `ActivityList recordType=... recordId=...` | `frontend/src/components/ActivityList.tsx` |
| GET loading | yes — `useApi(path, refreshKey)` | `frontend/src/useApi.ts` |

## 3. Backend: model, schemas, handlers — `backend/app/<tool>.py`

1. SQLAlchemy model (`Mapped[...]` columns). Put real invariants in the database (`unique=True`, non-null).
2. Register the module in `create_tables()` in `db.py` and include its router in `main.py`.
3. A `TRANSITIONS: dict[str, dict[str, str]]` table and, if needed, a `NOTE_REQUIRED` set.
4. Pydantic request schemas with `Literal[...]` actions, length limits, regex patterns; blank-note rules in a
   `model_validator` so violations return 422.
5. Routes:
   - `GET /api/<tool>` with validated filter params and `limit: Query(ge=1, le=100)`; parameterized ORM queries only.
   - `GET /api/<tool>/{id}` → 404 when missing; return `allowed_actions` for UI convenience.
   - `POST /api/<tool>/{id}/decision` depends on `Reviewer` (401/403 come from the dependency). Look up the
     transition → 409 if not allowed. Update the record and call `record_activity(...)`, then a **single**
     `db.commit()` so the change and its history land in one transaction.
6. Never read a role or actor from the request body; always use the dependency's identity.

## 4. Tests — `backend/tests/test_<tool>.py`

Use the `viewer` / `reviewer` / `anon` fixtures in `conftest.py`. At minimum:
viewer mutation → 403 and data unchanged; valid action → status changes + activity row; invalid transition → 409;
required note → 422; any idempotency/uniqueness rule (e.g. replay returns the same record).
Add seed rows for the tool in `backend/app/seed.py` (fictional data only).

## 5. Frontend — `frontend/src/<tool>/`

1. `types.ts`: record/detail/list types, status list, note rules mirrored from the backend (convenience only).
2. `<Tool>Page.tsx`: columns (`Column<T>[]`), filters, `useApi` for list and detail, `DetailPanel` fields,
   `DecisionForm`, `ActivityList`. Keep labels, columns, layout here — not in shared components.
3. Register navigation in `PAGES` and the page switch in `frontend/src/App.tsx`.

## 6. Verify the full path

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run typecheck && npm run build
cd backend && .venv/bin/python -m app.seed --reset
```

Then in the browser: as viewer, confirm read-only; as reviewer, filter, open a record, act, check history; refresh and
restart the API to confirm persistence. Record what you ran in `docs/build-notes.md`.

## When the existing patterns don't fit

Write ordinary, explicit code in the tool's own module rather than bending shared helpers:

- A different permission rule (e.g. a third role or amount threshold) → add a new dependency in `auth.py` next to
  `require_reviewer`, after the rule is agreed by an engineer. Keep it explicit; no policy DSL.
- A screen that is not a queue (e.g. a form-only intake page) → a plain component under `frontend/src/<tool>/`.
- An extra side effect (e.g. a calculation, an export) → a function in the tool module, called inside the handler
  before the single commit.
- Promote code into `components/` or a shared backend helper only when a **second** tool actually needs it.
