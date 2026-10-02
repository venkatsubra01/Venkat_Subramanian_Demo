import { useState, type FormEvent } from "react";
import { api, queryString, sourceHref, type Identity } from "../api";
import { DataTable, type Column } from "../components/DataTable";
import { DetailPanel, DetailPanelPlaceholder, PanelSection } from "../components/DetailPanel";
import { StatusBadge } from "../components/StatusBadge";
import { formatTimestamp, humanize } from "../format";
import { useApi } from "../useApi";
import {
  appLabel,
  fromLocalInput,
  PRIORITIES,
  SOURCE_APPS,
  toLocalInput,
  WORK_POLL_MS,
  type Assignee,
  type TaskList,
  type WorkTask,
} from "./types";

function Due({ task }: { task: WorkTask }) {
  if (!task.due_at) return <span className="muted">No deadline</span>;
  return (
    <span className={task.is_overdue ? "overdue" : undefined}>
      {formatTimestamp(task.due_at)}
      {task.is_overdue && <span className="overdue-tag">Overdue</span>}
    </span>
  );
}

const columns: Column<WorkTask>[] = [
  { key: "app", label: "App", render: (t) => appLabel(t.source_app) },
  {
    key: "case",
    label: "Case",
    render: (t) => (
      <>
        <a href={sourceHref(t.source_app, t.source_id)} onClick={(e) => e.stopPropagation()}>
          {t.source_id}
        </a>
        <div className="muted">{t.source_label}</div>
      </>
    ),
  },
  { key: "status", label: "Case status", render: (t) => <StatusBadge status={t.source_status} /> },
  { key: "assignee", label: "Assignee", render: (t) => t.assignee_name ?? <span className="muted">Unassigned</span> },
  { key: "priority", label: "Priority", render: (t) => <span className={`priority priority-${t.priority}`}>{t.priority}</span> },
  { key: "due", label: "Deadline", render: (t) => <Due task={t} /> },
];

function TaskEditor({ task, onSaved }: { task: WorkTask; onSaved: (task: WorkTask) => void }) {
  const assignees = useApi<Assignee[]>("/api/work/assignees");
  const [assignee, setAssignee] = useState(task.assignee_id ?? "");
  const [priority, setPriority] = useState<string>(task.priority);
  const [due, setDue] = useState(toLocalInput(task.due_at));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    const body: Record<string, string | null> = {};
    if ((assignee || null) !== task.assignee_id) body.assignee_id = assignee || null;
    if (priority !== task.priority) body.priority = priority;
    if (due !== toLocalInput(task.due_at)) body.due_at = fromLocalInput(due);
    if (Object.keys(body).length === 0) {
      setError("Nothing changed.");
      return;
    }
    if (reason.trim()) body.reason = reason.trim();
    setSaving(true);
    setError(null);
    try {
      onSaved(await api<WorkTask>(`/api/work/tasks/${task.id}`, { method: "PATCH", body }));
      setReason("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (task.state !== "active") return <div className="state">Completed with its case; no changes allowed.</div>;
  return (
    <form className="decision-form" onSubmit={save}>
      <fieldset disabled={saving}>
        <label className="note-field">
          Assignee (eligible employees only)
          <select value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Assignee">
            <option value="">Unassigned</option>
            {(assignees.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.role})
              </option>
            ))}
          </select>
        </label>
        <label className="note-field">
          Priority
          <select value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Priority">
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="note-field">
          Deadline (your local time; stored in UTC; demo target)
          <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Deadline" />
        </label>
        <label className="note-field">
          Reason (optional, recorded in the audit log)
          <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
        </label>
        {error && <div className="state state-error" role="alert">{error}</div>}
        <button type="submit">{saving ? "Saving…" : "Save task"}</button>
      </fieldset>
    </form>
  );
}

/** `mode="all"`: supervisor Work List. `mode="mine"`: the signed-in employee's My Work. */
export function WorkPage({ user, mode }: { user: Identity; mode: "all" | "mine" }) {
  const [app, setApp] = useState("");
  const [assignee, setAssignee] = useState("");
  const [priority, setPriority] = useState("");
  const [unassigned, setUnassigned] = useState(false);
  const [overdue, setOverdue] = useState(false);
  const [state, setState] = useState("active");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const supervisorView = mode === "all";
  const assignees = useApi<Assignee[]>(supervisorView ? "/api/work/assignees" : null);
  const path = supervisorView
    ? `/api/work/tasks${queryString({
        app,
        assignee_id: assignee,
        priority,
        state,
        unassigned: unassigned ? "true" : undefined,
        overdue: overdue ? "true" : undefined,
      })}`
    : `/api/work/mine${queryString({ state })}`;
  const list = useApi<TaskList>(supervisorView && !user.can_supervise ? null : path, refreshKey, 0, WORK_POLL_MS);
  const selected = list.data?.items.find((t) => t.id === selectedId) ?? null;

  if (supervisorView && !user.can_supervise) {
    return <div className="state">The Work List is for supervisors. Switch to a supervisor demo identity.</div>;
  }

  return (
    <div className="workflow">
      <section className="queue">
        <div className="queue-header">
          <h1>{supervisorView ? "Work List (all apps)" : `My Work — ${user.name}`}</h1>
          {list.data && (
            <div className="summary">
              <strong>{list.data.total}</strong> tasks ·{" "}
              <strong className={list.data.overdue_count ? "overdue" : undefined}>{list.data.overdue_count}</strong> overdue
              {supervisorView && <> · {list.data.unassigned_count} unassigned</>}
            </div>
          )}
        </div>
        <p className="muted">
          One task per actionable case. Case status lives in each app; a task completes when its case does. Refreshes every{" "}
          {WORK_POLL_MS / 1000}s. Deadlines are demo operational targets.
          {!supervisorView && " Opening a case still uses that app's own permissions."}
        </p>
        <div className="filters">
          {supervisorView && (
            <>
              <select value={app} onChange={(e) => setApp(e.target.value)} aria-label="App filter">
                <option value="">All apps</option>
                {SOURCE_APPS.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label}
                  </option>
                ))}
              </select>
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Assignee filter">
                <option value="">Any assignee</option>
                {(assignees.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <select value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Priority filter">
                <option value="">Any priority</option>
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              <label className="checkbox-filter">
                <input type="checkbox" checked={unassigned} onChange={(e) => setUnassigned(e.target.checked)} />
                Unassigned
              </label>
              <label className="checkbox-filter">
                <input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} />
                Overdue
              </label>
            </>
          )}
          <select value={state} onChange={(e) => setState(e.target.value)} aria-label="Task state filter">
            <option value="active">Active</option>
            <option value="completed">Completed</option>
            <option value="all">All</option>
          </select>
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items ?? []}
          rowKey={(t) => String(t.id)}
          rowClassName={(t) => (t.is_overdue ? "row-overdue" : undefined)}
          selectedKey={selectedId === null ? null : String(selectedId)}
          onSelect={supervisorView ? (t) => setSelectedId(t.id) : undefined}
          loading={list.loading}
          error={list.error}
          emptyMessage={supervisorView ? "No tasks match these filters." : "Nothing assigned to you."}
        />
      </section>
      {supervisorView &&
        selectedId !== null &&
        (selected ? (
          <DetailPanel
            title={`Task ${selected.id}`}
            subtitle={`${appLabel(selected.source_app)} · ${selected.source_id}`}
            onClose={() => setSelectedId(null)}
            fields={[
              {
                label: "Source case",
                value: <a href={sourceHref(selected.source_app, selected.source_id)}>{selected.source_label}</a>,
              },
              { label: "Case status (owned by the app)", value: <StatusBadge status={selected.source_status} /> },
              { label: "Task", value: `${humanize(selected.kind)} · ${selected.state}` },
              { label: "Deadline", value: <Due task={selected} /> },
              { label: "Created", value: formatTimestamp(selected.created_at) },
            ]}
          >
            <PanelSection title="Assignment, priority and deadline">
              <TaskEditor
                key={`${selected.id}-${selected.updated_at}`}
                task={selected}
                onSaved={() => setRefreshKey((k) => k + 1)}
              />
            </PanelSection>
          </DetailPanel>
        ) : (
          <DetailPanelPlaceholder error={list.error} />
        ))}
    </div>
  );
}
