import { useState } from "react";
import { queryString, sourceHref, type ActivityEntry, type Identity } from "../api";
import { formatChange } from "../components/ActivityList";
import { DataTable, type Column } from "../components/DataTable";
import { formatTimestamp, humanize } from "../format";
import { useApi } from "../useApi";
import { SOURCE_APPS } from "../work/types";

type AuditPageData = { items: ActivityEntry[]; total: number; page: number; page_size: number };

const PAGE_SIZE = 25;
const EMPTY_FILTERS = { app: "", record_id: "", actor_id: "", action: "", category: "", request_id: "", task_id: "", approval_id: "" };
type Filters = typeof EMPTY_FILTERS;

export function AuditPage({ user }: { user: Identity }) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const params: Record<string, string> = { page: String(page), page_size: String(PAGE_SIZE) };
  for (const [key, value] of Object.entries(filters)) if (value.trim()) params[key] = value.trim();
  const data = useApi<AuditPageData>(user.can_supervise ? `/api/audit${queryString(params)}` : null, 0, 250);

  if (!user.can_supervise) {
    return <div className="state">The Audit Log is for supervisors. Switch to a supervisor demo identity.</div>;
  }

  function set(key: keyof Filters, value: string) {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  }

  const filterLink = (key: keyof Filters, value: string | number | null, label?: string) =>
    value === null ? null : (
      <button type="button" className="link-button inline" onClick={() => set(key, String(value))} title={`Filter by ${key}`}>
        {label ?? String(value)}
      </button>
    );

  const columns: Column<ActivityEntry>[] = [
    { key: "time", label: "Server time", render: (e) => formatTimestamp(e.created_at) },
    { key: "actor", label: "Actor", render: (e) => filterLink("actor_id", e.actor_id, e.actor_name) },
    {
      key: "record",
      label: "Record",
      render: (e) => (
        <>
          <a href={sourceHref(e.record_type, e.record_id)}>{e.record_id}</a>
          <div className="muted">{e.record_type}</div>
        </>
      ),
    },
    {
      key: "action",
      label: "Action",
      render: (e) => (
        <>
          {humanize(e.action)}
          <div className="muted">{e.category}</div>
        </>
      ),
    },
    { key: "change", label: "Change / reason", render: (e) => <span className="audit-change">{[formatChange(e), e.note].filter(Boolean).join(" — ")}</span> },
    {
      key: "refs",
      label: "Links",
      render: (e) => (
        <span className="audit-refs">
          {e.task_id !== null && <>task {filterLink("task_id", e.task_id)} </>}
          {e.approval_id !== null && <>approval {filterLink("approval_id", e.approval_id)} </>}
          {e.request_id && <>req {filterLink("request_id", e.request_id, e.request_id.slice(-6))}</>}
        </span>
      ),
    },
  ];

  const totalPages = data.data ? Math.max(1, Math.ceil(data.data.total / PAGE_SIZE)) : 1;
  return (
    <section className="queue">
      <div className="queue-header">
        <h1>Audit log</h1>
        {data.data && <div className="summary">{data.data.total} entries</div>}
      </div>
      <p className="muted">
        Application-level append-only: the API has no edit or delete operations and corrections are new entries. It is not
        immutable against someone with direct database access. Newest first; times are server UTC shown in your local zone.
      </p>
      <div className="filters">
        <select value={filters.app} onChange={(e) => set("app", e.target.value)} aria-label="App filter">
          <option value="">All apps</option>
          {SOURCE_APPS.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>
        <select value={filters.category} onChange={(e) => set("category", e.target.value)} aria-label="Category filter">
          <option value="">All categories</option>
          <option value="case">Case changes</option>
          <option value="work">Work management</option>
          <option value="access">Sensitive views/downloads</option>
        </select>
        <input placeholder="Record ID" value={filters.record_id} maxLength={64} onChange={(e) => set("record_id", e.target.value)} aria-label="Record ID filter" />
        <input placeholder="Actor ID" value={filters.actor_id} maxLength={32} onChange={(e) => set("actor_id", e.target.value)} aria-label="Actor filter" />
        <input placeholder="Action" value={filters.action} maxLength={64} onChange={(e) => set("action", e.target.value)} aria-label="Action filter" />
        <input placeholder="Request ID" value={filters.request_id} maxLength={64} onChange={(e) => set("request_id", e.target.value)} aria-label="Request ID filter" />
        <input placeholder="Task ID" value={filters.task_id} inputMode="numeric" onChange={(e) => set("task_id", e.target.value.replace(/\D/g, ""))} aria-label="Task ID filter" />
        <input placeholder="Approval ID" value={filters.approval_id} inputMode="numeric" onChange={(e) => set("approval_id", e.target.value.replace(/\D/g, ""))} aria-label="Approval ID filter" />
        <button type="button" className="secondary" onClick={() => { setFilters(EMPTY_FILTERS); setPage(1); }}>
          Clear
        </button>
      </div>
      <DataTable
        columns={columns}
        rows={data.data?.items ?? []}
        rowKey={(e) => String(e.id)}
        loading={data.loading}
        error={data.error}
        emptyMessage="No audit entries match these filters."
      />
      <div className="pagination">
        <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {totalPages}
        </span>
        <button type="button" className="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
          Next
        </button>
      </div>
    </section>
  );
}
