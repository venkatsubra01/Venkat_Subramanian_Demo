import { useState } from "react";
import { api, queryString, type Identity } from "../api";
import { ActivityList } from "../components/ActivityList";
import { CaseTask } from "../components/CaseTask";
import { DataTable, type Column } from "../components/DataTable";
import { DecisionForm } from "../components/DecisionForm";
import { DetailPanel, DetailPanelPlaceholder, PanelSection } from "../components/DetailPanel";
import { StatusBadge } from "../components/StatusBadge";
import { formatTimestamp, humanize } from "../format";
import { useApi } from "../useApi";
import { KYC_NOTE_REQUIRED, KYC_STATUSES, RISK_LABELS, type KycCase, type KycCaseDetail, type KycList } from "./types";

const columns: Column<KycCase>[] = [
  { key: "id", label: "Case", render: (c) => c.id },
  { key: "customer_name", label: "Customer", render: (c) => c.customer_name },
  { key: "submitted_at", label: "Submitted", render: (c) => formatTimestamp(c.submitted_at) },
  { key: "risk_label", label: "Risk", render: (c) => <span className={`risk risk-${c.risk_label}`}>{c.risk_label}</span> },
  { key: "status", label: "Status", render: (c) => <StatusBadge status={c.status} /> },
];

export function KycPage({ user, initialId = null }: { user: Identity; initialId?: string | null }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [risk, setRisk] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [refreshKey, setRefreshKey] = useState(0);

  const list = useApi<KycList>(`/api/kyc${queryString({ search: search.trim(), status, risk })}`, refreshKey, 200);
  const detail = useApi<KycCaseDetail>(
    selectedId ? `/api/kyc/${encodeURIComponent(selectedId)}` : null,
    refreshKey,
  );

  async function submitDecision(action: string, note: string) {
    if (!selectedId) return;
    const updated = await api<KycCaseDetail>(`/api/kyc/${encodeURIComponent(selectedId)}/decision`, {
      method: "POST",
      body: { action, note: note.trim() || null },
    });
    detail.setData(updated);
    setRefreshKey((key) => key + 1);
  }

  const record = detail.data && detail.data.id === selectedId ? detail.data : null;

  return (
    <div className="workflow">
      <section className="queue">
        <div className="queue-header">
          <h1>KYC review queue</h1>
          {list.data && (
            <div className="summary" aria-label="Pending count">
              <strong>{list.data.status_counts.pending_review}</strong> pending review ·{" "}
              {list.data.status_counts.awaiting_information} awaiting information
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
          <select value={risk} onChange={(event) => setRisk(event.target.value)} aria-label="Risk filter">
            <option value="">All risk levels</option>
            {RISK_LABELS.map((r) => (
              <option key={r} value={r}>
                {r} risk
              </option>
            ))}
          </select>
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items ?? []}
          rowKey={(c) => c.id}
          selectedKey={selectedId}
          onSelect={(c) => setSelectedId(c.id)}
          loading={list.loading}
          error={list.error}
          emptyMessage="No KYC cases match these filters."
        />
      </section>
      {selectedId &&
        (record ? (
          <DetailPanel
            title={record.customer_name}
            subtitle={record.id}
            onClose={() => setSelectedId(null)}
            fields={[
              { label: "Status", value: <StatusBadge status={record.status} /> },
              { label: "Risk", value: record.risk_label },
              { label: "Submitted", value: formatTimestamp(record.submitted_at) },
              { label: "Check summary", value: record.check_summary },
            ]}
          >
            <PanelSection title="Work task">
              <CaseTask app="kyc" id={record.id} refreshKey={refreshKey} />
            </PanelSection>
            <PanelSection title="Decision">
              <DecisionForm
                key={`${record.id}-${record.status}`}
                allowedActions={record.allowed_actions}
                noteRequired={(action) => KYC_NOTE_REQUIRED.has(action)}
                canMutate={user.can_mutate}
                onSubmit={submitDecision}
              />
            </PanelSection>
            <PanelSection title="Activity history">
              <ActivityList recordType="kyc" recordId={record.id} refreshKey={refreshKey} />
            </PanelSection>
          </DetailPanel>
        ) : (
          <DetailPanelPlaceholder error={detail.error} />
        ))}
    </div>
  );
}
