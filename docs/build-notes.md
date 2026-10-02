# Build notes (evidence)

Measured outcomes only. No time-saved estimates.

## Session

- Devin Cloud session: https://app.devin.ai/sessions/f5089b762234400b9acc1def7adb881f
- Branch: `devin/1790827594-kyc-refunds-prototype`
- Clock: VM `date -u`, cross-checked against an external HTTP `Date` header (they agreed to the second).

## Prompts

The user sent **one message** containing the full implementation brief (KYC first, refunds second, 120-minute limit),
including both the "Initial Devin prompt" and the "Follow-up Devin prompt" text from section 10. Devin executed them in
order in the same session. The refund workflow was therefore **not** triggered by a separate follow-up message; it is
traceable as a separate commit (below) whose scope matches the follow-up prompt. If a separately-prompted follow-up is
required for evaluation, that step was not performed.

Initial prompt (from brief §10):
> Build the KYC workflow in this brief first, using the specified stack. Keep the app local and runnable. Start with a
> short plan, then implement and verify it. Report blockers and actual checks run. Commit the working KYC checkpoint
> before adding refunds. Follow the 120-minute total time limit; do not build a generic framework.

Follow-up prompt (from brief §10):
> Add the refund exception workflow described in the brief. Reuse the KYC table, detail layout, permission checks,
> database setup, and activity helper. Identify the reused files and new refund-specific code in your handoff. Verify
> that replaying an event creates only one exception.

## Timeline (UTC, 2026-10-01)

| Time | Event |
| --- | --- |
| 04:05 | Brief received; implementation started |
| 04:09:03 | Commit `43e93cf` — KYC checkpoint (queue, decisions, demo identity, permissions, activity) |
| 04:10:14 | Commit `53193be` — refund exception workflow |
| 04:10:24 | Commit `8191e4d` — small follow-up change: KYC risk filter |
| 04:11:05 | Commit `c0ed7ef` — README, build notes, recipe, skill; PR opened: https://github.com/venkatsubra01/Venkat_Subramanian_Demo/pull/1 |
| 04:11–04:22 | Browser checks (Devin testing agent, recorded) |
| ~04:23 | Fix found by browser check (stale replay banner) + notes update |

Elapsed to the refunds commit: ~5 minutes of wall-clock by the VM/external clock. Total elapsed is recorded in the
"Final status" section.

## Human interventions

None during implementation. The only input was the brief itself.

Automated workarounds (no human involved):
- `npm view <pkg> version --before=...` reported `vite@8.3.1`, but `npm install --before=2026-09-20` rejected it
  (published 2026-09-24). Pinned `vite@8.3.0` instead. All npm and pip versions were chosen to be published at least
  ~10 days before the build.

## Reused vs new code (refund follow-up, commit `53193be`)

Reused unchanged: `backend/app/auth.py` (`CurrentUser`, `Reviewer`), `backend/app/activity.py` (`record_activity`,
`GET /api/activity`), `frontend/src/components/DataTable.tsx`, `DecisionForm.tsx`, `ActivityList.tsx`,
`StatusBadge.tsx`, `IdentitySwitcher.tsx`, `frontend/src/api.ts`.

Shared files touched minimally: `backend/app/db.py` (register model), `backend/app/main.py` (include routers),
`backend/app/seed.py` (refund seed rows), `frontend/src/App.tsx` (nav item), `frontend/src/components/DetailPanel.tsx`
(added `DetailPanelPlaceholder`), `frontend/src/styles.css`.

Extracted when the second workflow needed it: `frontend/src/useApi.ts` (list/detail loading), with
`frontend/src/kyc/KycPage.tsx` refactored onto it.

New refund-specific code: `backend/app/refunds.py`, `backend/tests/test_refunds.py`,
`frontend/src/refunds/{types.ts,RefundsPage.tsx,SimulateRefundForm.tsx}`.

## Automated checks run (actual results)

| Command | Result |
| --- | --- |
| `cd backend && .venv/bin/python -m pytest -q` (after KYC commit) | 16 passed |
| `cd backend && .venv/bin/python -m pytest -q` (after refunds commit) | 31 passed |
| `cd backend && .venv/bin/python -m pytest -q` (after risk filter) | 32 passed |
| `cd frontend && npm run typecheck` | passed (no output) |
| `cd frontend && npm run build` | passed (`tsc -b && vite build`, 26 modules → dist) |

Brief §9 automated acceptance checks map to tests:
- viewer mutations fail, data unchanged → `test_viewer_cannot_decide_and_data_unchanged`, `test_viewer_cannot_decide`
  (refunds), `test_viewer_cannot_simulate_event`
- valid KYC decision changes status and writes activity → `test_valid_decision_changes_status_and_writes_activity`
- invalid transition fails → `test_invalid_transition_is_409_and_no_activity`, `test_resolved_is_terminal`
- required note enforced → `test_required_note_enforced`, `test_decisions_require_note`
- refund replay creates no duplicate → `test_replaying_event_returns_existing_without_duplicate`,
  `test_reused_event_id_with_different_fields_is_409`, `test_event_id_unique_constraint_in_database`

Manual API checks through the Vite proxy (curl, reviewer/viewer cookies): anonymous list → 401; viewer decision → 403;
reviewer request-information → 200 with activity row; `Origin: http://evil.example` mutation → 403; refund event
→ 201, identical replay → 200 same id, same id with different amount → 409.

## Browser checks

Run by Devin's testing agent in the session's Chrome against Vite (:5173) → FastAPI (:8000) → SQLite, recorded on
video (attached to the Devin session / PR comment). Starting state: `.venv/bin/python -m app.seed --reset`.

| Check | Result |
| --- | --- |
| Before choosing an identity, app shows "Choose a demo identity"; switcher labelled "Demo identity — no real login" | pass |
| Viewer: KYC queue (10 cases, 6 pending / 2 awaiting); case detail shows disabled decision form + read-only notice | pass |
| Viewer: same-origin `fetch` POST approve → 403, case stays `pending_review` | pass |
| Viewer: "Simulate failed refund" disabled | pass |
| Reviewer: name search, status filter, risk filter; impossible combination shows empty-state message | pass |
| Reviewer: blank Reject note blocked in UI; API probe → 422, status and activity unchanged | pass |
| Reviewer: KYC-1003 request information → return to review; badges, counts, history (actor, notes, transitions, timestamps) | pass |
| Reviewer: KYC-1001 approve with blank note; terminal "No further actions" | pass |
| Refunds: status filter (escalated → only RFX-SEED0002) | pass |
| Refunds: simulate event → created RFX-E07D2E66 (€12.50 / 1250 EUR), rows 3 → 4 | pass |
| Refunds: identical replay → same id, still 4 rows, one creation activity | pass |
| Refunds: same event id, amount 1251 → visible 409, stored amount unchanged | pass |
| Refunds: blank escalate note blocked; escalate → resolve; history = created_from_event, escalate, resolve, notification_simulated | pass |
| Page refresh keeps identity, decisions and history | pass |
| `fuser -k 8000/tcp` → queue shows error state (502 via proxy), not empty state | pass |
| Restart `uvicorn` without reseeding → all decisions and history retained | pass |

Issue found: after a successful replay, a following 409 left the earlier "Replay … no duplicate" banner visible next
to the error. Fixed in the follow-up commit (banner cleared when a new event is sent); verified by `npm run build`
only — not re-run in the browser.

Not exercised in the browser (covered by pytest instead): reject-to-terminal, cross-origin and tampered-cookie
rejection, viewer refund decision API. Concurrent review was not tested (documented gap).

## Small follow-up change (commit `8191e4d`)

KYC risk filter: `risk` query param (`low|medium|high`, validated by `Literal`) in `backend/app/kyc.py`, a select in
`frontend/src/kyc/KycPage.tsx`, and `test_risk_filter`. Diff: 4 files, +22/−2. Verified by pytest (32 passed) and
`npm run build`.

## Unfinished work / known gaps

- Concurrent review protection (documented gap; no optimistic locking).
- Activity history is not tamper-proof; notifications are a local activity line only.
- No frontend unit tests; frontend is covered by type/build check and the browser pass.
- Not deployed by design; no SSO, monitoring, backups.

## Final status

- KYC workflow: complete and verified (pytest + browser).
- Refund workflow: complete and verified (pytest + browser), including event replay.
- Small follow-up change (risk filter): done.
- Docs: README, this file, `docs/adding-a-tool.md`, `.agents/skills/add-internal-tool/SKILL.md`.
- Elapsed wall-clock from start (04:05) to final notes commit: ~19 minutes by VM/external clock, well under the
  120-minute limit. Human interventions: none.
- The Key Decisions one-pager is owned outside this repo; reconcile it against the README "Security model and known
  gaps" and this file before submission.

## Chargeback evidence workspace (second follow-up request, 2026-10-02)

Branch `devin/1790912373-chargebacks` (based on `29b1789`). Triggered by a **separate user message** asking for a
chargeback evidence workspace (disputes queue with overdue highlighting, linked payment/customer/refund detail, checklist,
notes, attachments, PDF evidence summary, Open → Collecting evidence → Ready for review → Closed with a closing outcome).

### Timeline (UTC, VM clock)

| Time | Event |
| --- | --- |
| ~03:38 | Request received; read `docs/adding-a-tool.md`, the repository skill, shared backend/frontend code |
| 03:39 | Branch created |
| 03:41 | Backend + tests passing (61 passed) |
| 03:42 | Frontend typecheck/build passing; manual API/PDF checks against a running server |
| 03:42 | Commits `513b66e` (API) and `facf770` (UI); browser pass handed to the testing agent |

### Design decisions made without asking (documented, easy to change)

- **Payments table** (`backend/app/payments.py`): the existing data had no payment or customer records, only payment
  references on refunds. A small seeded `payments` table links a reference to a KYC case. Refund history is looked up by
  payment reference, so refunds created later by the demo event also appear.
- **No PDF dependency**: a ~100-line text-only writer (`backend/app/pdf.py`) instead of adding a library. Output was parsed
  with `pypdf==5.4.0` in strict mode as an external check (installed outside the repo, not a project dependency).
- **Attachments**: PDF/PNG/JPEG/TXT, 5 MB, 20 per case; reviewer uploads, any session downloads; no delete. Closed cases
  are read-only (409).
- **Workflow**: strictly linear as requested; close only from `ready_for_review`; outcome ∈ won/lost/accepted/withdrawn.

### Automated checks run (actual results)

```
$ cd backend && .venv/bin/python -m pytest -q
61 passed in 2.74s            # 32 existing KYC/refund/auth tests unchanged + 29 new in tests/test_chargebacks.py
$ cd frontend && npm run typecheck && npm run build
tsc -b                        # no errors
dist/assets/index-*.js 247.17 kB │ gzip: 75.77 kB   ✓ built
```

New tests cover: 401 without session; list columns, status/overdue filters and counts; linked payment, KYC customer and
refund history (including a refund created later by the demo event); explicit missing-information messages; viewer 403 on
decision/checklist/notes/upload with data and activity unchanged (and role-in-body ignored); cross-origin 403; full
workflow with activity rows; invalid transitions 409; missing/invalid outcome 422; checklist/notes persistence and
activity (no-op writes not logged); closed case read-only; upload round trip with path-traversal filename sanitised;
case-scoped attachment ids; rejected types, extension mismatch, content sniff, empty file and >5 MB; PDF content
(sections, disclaimer, refund history, notes, inventory, activity) and missing-info PDF.

### Manual API checks against a running server (curl, after `app.seed --reset`)

anon list 401 · viewer notes PUT 403 · viewer upload 403 · reviewer `.txt` upload 201 · `.exe` 415 · 6 MB PDF 413 ·
start_collecting 200 · mark_ready 200 · close without outcome 422 · close with outcome 200 · **API restarted** → status,
outcome, notes, checklist and attachment all retained · viewer download 200 and byte-identical · anon download 401 ·
activity: attachment_uploaded, notes_updated, checklist_completed, start_collecting, mark_ready, close · CBK-2001 links
RFX-SEED0001 and KYC-1004 · three summary PDFs parsed by `pypdf` (strict) with disclaimer and attachment inventory present.

### Browser checks

Run by Devin's testing agent in Chrome against Vite (5173) → FastAPI (8000), after `app.seed --reset`, with a recording.
All requested checks passed:

- Viewer: required columns; only CBK-2001 and CBK-2005 flagged overdue (closed CBK-2006 not); status filter and
  "Overdue only" combine correctly, including an empty result. Checklist disabled, notes read-only, no upload or save
  controls, read-only workflow notice; attachment and PDF downloads work.
- Links: CBK-2001 shows payment and RFX-SEED0001; customer link opens KYC-1004 and refund link opens RFX-SEED0001.
  CBK-2005/2006 show explicit missing-information notices.
- Reviewer on CBK-2002: two checklist items and notes saved with actor/time in history; `.txt` upload downloaded
  byte-identical (sha256 compared); `.html` upload shows the 415 message and creates no attachment.
- Workflow: Open → Collecting evidence → Ready for review → Closed; blank outcome refused in the UI with status unchanged;
  closing as "won" shows the outcome and makes evidence read-only.
- PDF: viewer and closed-case PDFs render in Chrome and parse with pypdf; contain case details, payment/customer/refund
  data, checklist, exact notes, attachment inventory with SHA-256, activity and "NOT A SUBMISSION PACKAGE".
- Persistence: refresh and API restart (no reseed) kept status/outcome, checklist, notes, attachment and seven activity
  entries; post-restart download still byte-identical.
- Regression: KYC search/status/risk filters and detail; Refunds status filter and detail.

Observed, not fixed: the PDF's last wrapped activity line can spill alone onto page 2 (content intact).
Not browser-tested (covered by pytest/curl instead): direct API permission bypass, upload size limits, concurrent edits.

### Elapsed time and interventions

About 16 minutes of VM wall-clock (~03:38 request → 03:54 docs commit), including the browser pass. No human intervention.

### Unresolved issues

- PDF pagination is simple (no keep-together); non-cp1252 characters print as `?`.
- No attachment delete/versioning, virus scanning, or concurrency protection; see README "Chargeback limitations".
