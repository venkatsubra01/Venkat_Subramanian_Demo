import { useState, type FormEvent } from "react";
import { api, queryString, sourceHref, type Identity } from "../api";
import { DataTable, type Column } from "../components/DataTable";
import { DetailPanel, DetailPanelPlaceholder, PanelSection } from "../components/DetailPanel";
import { StatusBadge } from "../components/StatusBadge";
import { formatTimestamp, humanize } from "../format";
import { useApi } from "../useApi";
import { WORK_POLL_MS } from "../work/types";
import { SnapshotView } from "./SnapshotView";
import type { ApprovalInbox, ApprovalInboxItem } from "./types";

const columns: Column<ApprovalInboxItem>[] = [
  { key: "id", label: "Request", render: (a) => `#${a.id}` },
  {
    key: "case",
    label: "Chargeback",
    render: (a) => (
      <>
        <a href={sourceHref(a.source_app, a.source_id)} onClick={(e) => e.stopPropagation()}>
          {a.source_id}
        </a>
        <div className="muted">{a.source_label}</div>
      </>
    ),
  },
  { key: "version", label: "Evidence", render: (a) => `v${a.evidence_version}` },
  { key: "by", label: "Requested by", render: (a) => a.requested_by_name },
  { key: "at", label: "Requested", render: (a) => formatTimestamp(a.requested_at) },
  { key: "state", label: "State", render: (a) => <StatusBadge status={a.state} /> },
];

function DecisionForm({ item, user, onDone }: { item: ApprovalInboxItem; user: Identity; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const own = item.requested_by_id === user.id;

  async function decide(approve: boolean, event?: FormEvent) {
    event?.preventDefault();
    if (!approve && !reason.trim()) {
      setError("An explanation is required to return evidence.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const base = `/api/chargebacks/${encodeURIComponent(item.source_id)}/approval-requests/${item.id}`;
      await api(`${base}/${approve ? "approve" : "return"}`, {
        method: "POST",
        body: approve
          ? { evidence_version: item.evidence_version }
          : { evidence_version: item.evidence_version, reason: reason.trim() },
      });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="decision-form" onSubmit={(e) => decide(false, e)}>
      {own && <p className="notice">You requested this approval; another supervisor must decide it.</p>}
      <fieldset disabled={saving || own}>
        <p className="muted">
          You are deciding on evidence v{item.evidence_version}. If the evidence changed since, the server rejects the decision.
          Approval sets the case to “ready for submission”, an internal status; nothing is sent to a payment provider.
        </p>
        <button type="button" onClick={() => decide(true)}>
          {saving ? "Saving…" : `Approve evidence v${item.evidence_version}`}
        </button>
        <label className="note-field">
          Explanation (required to return)
          <textarea value={reason} rows={2} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" className="secondary">
          Return to reviewer
        </button>
        {error && <div className="state state-error" role="alert">{error}</div>}
      </fieldset>
    </form>
  );
}

export function ApprovalsPage({ user }: { user: Identity }) {
  const [state, setState] = useState("pending");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const inbox = useApi<ApprovalInbox>(
    user.can_supervise ? `/api/approvals${queryString({ state })}` : null,
    refreshKey,
    0,
    WORK_POLL_MS,
  );
  if (!user.can_supervise) {
    return <div className="state">Approvals are for supervisors. Switch to a supervisor demo identity.</div>;
  }
  const selected = inbox.data?.items.find((a) => a.id === selectedId) ?? null;

  return (
    <div className="workflow">
      <section className="queue">
        <div className="queue-header">
          <h1>Approval inbox</h1>
          {inbox.data && (
            <div className="summary">
              <strong>{inbox.data.state_counts.pending}</strong> pending · {inbox.data.state_counts.approved} approved ·{" "}
              {inbox.data.state_counts.returned} returned · {inbox.data.state_counts.invalidated} invalidated
            </div>
          )}
        </div>
        <p className="muted">
          Chargeback evidence approvals. The inbox coordinates; the chargeback app enforces who may decide and which version.
        </p>
        <div className="filters">
          <select value={state} onChange={(e) => setState(e.target.value)} aria-label="Approval state filter">
            {["pending", "approved", "returned", "invalidated", "all"].map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </div>
        <DataTable
          columns={columns}
          rows={inbox.data?.items ?? []}
          rowKey={(a) => String(a.id)}
          selectedKey={selectedId === null ? null : String(selectedId)}
          onSelect={(a) => setSelectedId(a.id)}
          loading={inbox.loading}
          error={inbox.error}
          emptyMessage="No approval requests in this state."
        />
      </section>
      {selectedId !== null &&
        (selected ? (
          <DetailPanel
            title={`Approval request #${selected.id}`}
            subtitle={`${selected.source_id} · evidence v${selected.evidence_version}`}
            onClose={() => setSelectedId(null)}
            fields={[
              { label: "Chargeback", value: <a href={sourceHref(selected.source_app, selected.source_id)}>{selected.source_label}</a> },
              { label: "Current case status", value: <StatusBadge status={selected.source_status} /> },
              { label: "Requested", value: `${selected.requested_by_name} · ${formatTimestamp(selected.requested_at)}` },
              { label: "State", value: <StatusBadge status={selected.state} /> },
            ]}
          >
            {selected.decided_by_name && (
              <p className="muted">
                Decided by {selected.decided_by_name}
                {selected.decided_at && ` · ${formatTimestamp(selected.decided_at)}`}
                {selected.decision_reason && `: ${selected.decision_reason}`}
              </p>
            )}
            {selected.invalidated_reason && <p className="notice">Invalidated: {selected.invalidated_reason}</p>}
            <PanelSection title={`Evidence submitted (v${selected.evidence_version})`}>
              <SnapshotView snapshot={selected.snapshot} />
            </PanelSection>
            {selected.state === "pending" && (
              <PanelSection title="Decision">
                <DecisionForm
                  key={selected.id}
                  item={selected}
                  user={user}
                  onDone={() => setRefreshKey((k) => k + 1)}
                />
              </PanelSection>
            )}
          </DetailPanel>
        ) : (
          <DetailPanelPlaceholder error={inbox.error} />
        ))}
    </div>
  );
}
