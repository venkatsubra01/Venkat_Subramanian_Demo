import { useCallback, useEffect, useState } from "react";
import { api, queryString, type Identity } from "../api";
import { ActivityList } from "../components/ActivityList";
import { DataTable, type Column } from "../components/DataTable";
import { DecisionForm } from "../components/DecisionForm";
import { DetailPanel, PanelSection } from "../components/DetailPanel";
import { StatusBadge } from "../components/StatusBadge";
import { formatTimestamp, humanize } from "../format";
import { KYC_NOTE_REQUIRED, KYC_STATUSES, type KycCase, type KycCaseDetail, type KycList } from "./types";

const columns: Column<KycCase>[] = [
  { key: "id", label: "Case", render: (c) => c.id },
  { key: "customer_name", label: "Customer", render: (c) => c.customer_name },
  { key: "submitted_at", label: "Submitted", render: (c) => formatTimestamp(c.submitted_at) },
  { key: "risk_label", label: "Risk", render: (c) => <span className={`risk risk-${c.risk_label}`}>{c.risk_label}</span> },
  { key: "status", label: "Status", render: (c) => <StatusBadge status={c.status} /> },
];

export function KycPage({ user }: { user: Identity }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [list, setList] = useState<KycList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KycCaseDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      setList(await api<KycList>(`/api/kyc${queryString({ search: search.trim(), status })}`));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [search, status]);

  useEffect(() => {
    const timer = setTimeout(loadList, 200);
    return () => clearTimeout(timer);
  }, [loadList, refreshKey]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailError(null);
    api<KycCaseDetail>(`/api/kyc/${encodeURIComponent(selectedId)}`)
      .then((data) => !cancelled && setDetail(data))
      .catch((err: Error) => !cancelled && setDetailError(err.message));
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  async function submitDecision(action: string, note: string) {
    if (!detail) return;
    const updated = await api<KycCaseDetail>(`/api/kyc/${encodeURIComponent(detail.id)}/decision`, {
      method: "POST",
      body: { action, note: note.trim() || null },
    });
    setDetail(updated);
    setRefreshKey((key) => key + 1);
  }

  return (
    <div className="workflow">
      <section className="queue">
        <div className="queue-header">
          <h1>KYC review queue</h1>
          {list && (
            <div className="summary" aria-label="Pending count">
              <strong>{list.status_counts.pending_review}</strong> pending review ·{" "}
              {list.status_counts.awaiting_information} awaiting information
            </div>
          )}
        </div>
        <div className="filters">
          <input
            type="search"
            placeholder="Search customer name"
            value={search}
            maxLength={100}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search customer name"
          />
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Status filter">
            <option value="">All statuses</option>
            {KYC_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </div>
        <DataTable
          columns={columns}
          rows={list?.items ?? []}
          rowKey={(c) => c.id}
          selectedKey={selectedId}
          onSelect={(c) => setSelectedId(c.id)}
          loading={loading}
          error={error}
          emptyMessage="No KYC cases match these filters."
        />
      </section>
      {selectedId && (
        detailError ? (
          <aside className="detail-panel"><div className="state state-error" role="alert">{detailError}</div></aside>
        ) : detail ? (
          <DetailPanel
            title={detail.customer_name}
            subtitle={detail.id}
            onClose={() => setSelectedId(null)}
            fields={[
              { label: "Status", value: <StatusBadge status={detail.status} /> },
              { label: "Risk", value: detail.risk_label },
              { label: "Submitted", value: formatTimestamp(detail.submitted_at) },
              { label: "Check summary", value: detail.check_summary },
            ]}
          >
            <PanelSection title="Decision">
              <DecisionForm
                key={`${detail.id}-${detail.status}`}
                allowedActions={detail.allowed_actions}
                noteRequired={(action) => KYC_NOTE_REQUIRED.has(action)}
                canMutate={user.can_mutate}
                onSubmit={submitDecision}
              />
            </PanelSection>
            <PanelSection title="Activity history">
              <ActivityList recordType="kyc" recordId={detail.id} refreshKey={refreshKey} />
            </PanelSection>
          </DetailPanel>
        ) : (
          <aside className="detail-panel"><div className="state">Loading case…</div></aside>
        )
      )}
    </div>
  );
}
