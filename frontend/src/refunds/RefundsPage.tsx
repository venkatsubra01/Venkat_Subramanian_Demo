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
import { SimulateRefundForm } from "./SimulateRefundForm";
import {
  formatMinorUnits,
  REFUND_STATUSES,
  type RefundDetail,
  type RefundEventResult,
  type RefundException,
  type RefundList,
} from "./types";

const columns: Column<RefundException>[] = [
  { key: "id", label: "Exception", render: (r) => r.id },
  { key: "payment_reference", label: "Payment ref", render: (r) => r.payment_reference },
  { key: "amount", label: "Amount", render: (r) => formatMinorUnits(r.amount_minor, r.currency) },
  { key: "failure_reason", label: "Failure reason", render: (r) => r.failure_reason },
  { key: "created_at", label: "Created", render: (r) => formatTimestamp(r.created_at) },
  { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
];

export function RefundsPage({ user, initialId = null }: { user: Identity; initialId?: string | null }) {
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [refreshKey, setRefreshKey] = useState(0);
  const [simulating, setSimulating] = useState(false);
  const [eventMessage, setEventMessage] = useState<string | null>(null);

  const list = useApi<RefundList>(`/api/refunds${queryString({ status })}`, refreshKey);
  const detail = useApi<RefundDetail>(
    selectedId ? `/api/refunds/${encodeURIComponent(selectedId)}` : null,
    refreshKey,
  );

  async function submitDecision(action: string, note: string) {
    if (!selectedId) return;
    const updated = await api<RefundDetail>(`/api/refunds/${encodeURIComponent(selectedId)}/decision`, {
      method: "POST",
      body: { action, note: note.trim() },
    });
    detail.setData(updated);
    setRefreshKey((key) => key + 1);
  }

  function handleEventResult(result: RefundEventResult) {
    setEventMessage(
      result.created
        ? `Created ${result.exception.id} from event ${result.exception.external_event_id}.`
        : `Replay: event ${result.exception.external_event_id} already exists as ${result.exception.id}; no duplicate created.`,
    );
    setSelectedId(result.exception.id);
    setRefreshKey((key) => key + 1);
  }

  const record = detail.data && detail.data.id === selectedId ? detail.data : null;

  return (
    <div className="workflow">
      <section className="queue">
        <div className="queue-header">
          <h1>Refund exceptions</h1>
          {list.data && (
            <div className="summary">
              <strong>{list.data.status_counts.open}</strong> open · {list.data.status_counts.escalated} escalated
            </div>
          )}
        </div>
        <div className="filters">
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Status filter">
            <option value="">All statuses</option>
            {REFUND_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setSimulating(true)}
            disabled={!user.can_mutate}
            title={user.can_mutate ? undefined : "Only the reviewer identity can simulate events"}
          >
            Simulate failed refund
          </button>
        </div>
        {simulating && <SimulateRefundForm
            onSending={() => setEventMessage(null)}
            onResult={handleEventResult}
            onCancel={() => setSimulating(false)}
          />}
        {eventMessage && <div className="notice" role="status">{eventMessage}</div>}
        <DataTable
          columns={columns}
          rows={list.data?.items ?? []}
          rowKey={(r) => r.id}
          selectedKey={selectedId}
          onSelect={(r) => setSelectedId(r.id)}
          loading={list.loading}
          error={list.error}
          emptyMessage="No refund exceptions match this filter."
        />
      </section>
      {selectedId &&
        (record ? (
          <DetailPanel
            title={formatMinorUnits(record.amount_minor, record.currency)}
            subtitle={record.id}
            onClose={() => setSelectedId(null)}
            fields={[
              { label: "Status", value: <StatusBadge status={record.status} /> },
              { label: "Payment reference", value: record.payment_reference },
              { label: "External event id", value: record.external_event_id },
              { label: "Amount (minor units)", value: `${record.amount_minor} ${record.currency}` },
              { label: "Failure reason", value: record.failure_reason },
              { label: "Created", value: formatTimestamp(record.created_at) },
            ]}
          >
            <PanelSection title="Work task">
              <CaseTask app="refund" id={record.id} refreshKey={refreshKey} />
            </PanelSection>
            <PanelSection title="Decision">
              <p className="muted">Resolving records an operational decision only. It never retries or issues a payment.</p>
              <DecisionForm
                key={`${record.id}-${record.status}`}
                allowedActions={record.allowed_actions}
                noteRequired={() => true}
                canMutate={user.can_mutate}
                onSubmit={submitDecision}
              />
            </PanelSection>
            <PanelSection title="Activity history">
              <ActivityList recordType="refund" recordId={record.id} refreshKey={refreshKey} />
            </PanelSection>
          </DetailPanel>
        ) : (
          <DetailPanelPlaceholder error={detail.error} />
        ))}
    </div>
  );
}
