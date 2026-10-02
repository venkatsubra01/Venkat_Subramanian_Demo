import { useState } from "react";
import { api, queryString, type Identity } from "../api";
import { ActivityList } from "../components/ActivityList";
import { DataTable, type Column } from "../components/DataTable";
import { DetailPanel, DetailPanelPlaceholder, PanelSection } from "../components/DetailPanel";
import { StatusBadge } from "../components/StatusBadge";
import { formatTimestamp, humanize } from "../format";
import { formatMinorUnits } from "../refunds/types";
import { useApi } from "../useApi";
import { ChargebackDecisionForm } from "./ChargebackDecisionForm";
import { Attachments, CaseNotes, EvidenceChecklist } from "./EvidenceSections";
import { CHARGEBACK_STATUSES, type Chargeback, type ChargebackDetail, type ChargebackList } from "./types";

function Deadline({ record }: { record: Chargeback }) {
  return (
    <span className={record.is_overdue ? "overdue" : undefined}>
      {formatTimestamp(record.evidence_due_at)}
      {record.is_overdue && <span className="overdue-tag">Overdue</span>}
    </span>
  );
}

const columns: Column<Chargeback>[] = [
  { key: "id", label: "Case", render: (c) => c.id },
  { key: "cardholder_name", label: "Customer", render: (c) => c.cardholder_name },
  { key: "payment_reference", label: "Payment ref", render: (c) => c.payment_reference },
  { key: "amount", label: "Disputed", render: (c) => formatMinorUnits(c.amount_minor, c.currency) },
  { key: "reason", label: "Reason", render: (c) => humanize(c.reason) },
  { key: "evidence_due_at", label: "Evidence deadline", render: (c) => <Deadline record={c} /> },
  { key: "status", label: "Status", render: (c) => <StatusBadge status={c.status} /> },
];

function Missing({ children }: { children: string }) {
  return <span className="missing">{children}</span>;
}

export function ChargebacksPage({ user, initialId = null }: { user: Identity; initialId?: string | null }) {
  const [status, setStatus] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [refreshKey, setRefreshKey] = useState(0);

  const list = useApi<ChargebackList>(
    `/api/chargebacks${queryString({ status, overdue: overdueOnly ? "true" : undefined })}`,
    refreshKey,
  );
  const detail = useApi<ChargebackDetail>(
    selectedId ? `/api/chargebacks/${encodeURIComponent(selectedId)}` : null,
    refreshKey,
  );

  function handleUpdated(updated: ChargebackDetail) {
    detail.setData(updated);
    setRefreshKey((key) => key + 1);
  }

  async function submitDecision(action: string, outcome: string | null, note: string) {
    if (!selectedId) return;
    handleUpdated(
      await api<ChargebackDetail>(`/api/chargebacks/${encodeURIComponent(selectedId)}/decision`, {
        method: "POST",
        body: { action, outcome, note: note.trim() || null },
      }),
    );
  }

  const record = detail.data && detail.data.id === selectedId ? detail.data : null;
  const editable = user.can_mutate && record?.status !== "closed";

  return (
    <div className="workflow">
      <section className="queue">
        <div className="queue-header">
          <h1>Chargeback disputes</h1>
          {list.data && (
            <div className="summary">
              <strong className={list.data.overdue_count ? "overdue" : undefined}>{list.data.overdue_count}</strong> overdue ·{" "}
              {list.data.status_counts.open} open · {list.data.status_counts.collecting_evidence} collecting ·{" "}
              {list.data.status_counts.ready_for_review} ready for review
            </div>
          )}
        </div>
        <p className="muted">
          Local demo with fictional disputes. Deadlines and evidence requirements are demo assumptions; nothing is sent to a
          payment provider.
        </p>
        <div className="filters">
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Status filter">
            <option value="">All statuses</option>
            {CHARGEBACK_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
          <label className="checkbox-filter">
            <input type="checkbox" checked={overdueOnly} onChange={(event) => setOverdueOnly(event.target.checked)} />
            Overdue only
          </label>
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items ?? []}
          rowKey={(c) => c.id}
          rowClassName={(c) => (c.is_overdue ? "row-overdue" : undefined)}
          selectedKey={selectedId}
          onSelect={(c) => setSelectedId(c.id)}
          loading={list.loading}
          error={list.error}
          emptyMessage="No disputes match these filters."
        />
      </section>
      {selectedId &&
        (record ? (
          <DetailPanel
            title={formatMinorUnits(record.amount_minor, record.currency)}
            subtitle={`${record.id} · ${humanize(record.reason)}`}
            onClose={() => setSelectedId(null)}
            fields={[
              {
                label: "Status",
                value: (
                  <>
                    <StatusBadge status={record.status} />
                    {record.outcome && <> outcome: <strong>{humanize(record.outcome)}</strong></>}
                  </>
                ),
              },
              { label: "Cardholder (as reported)", value: record.cardholder_name },
              { label: "Evidence deadline (demo assumption)", value: <Deadline record={record} /> },
              { label: "Opened", value: formatTimestamp(record.created_at) },
            ]}
          >
            {record.missing_information.length > 0 && (
              <div className="notice missing-info" role="status">
                <strong>Missing information</strong>
                <ul>
                  {record.missing_information.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            <PanelSection title="Payment">
              {record.payment ? (
                <dl className="detail-fields compact">
                  <div><dt>Reference</dt><dd>{record.payment.reference}</dd></div>
                  <div><dt>Captured</dt><dd>{formatMinorUnits(record.payment.amount_minor, record.payment.currency)} on {formatTimestamp(record.payment.captured_at)}</dd></div>
                  <div><dt>Card</dt><dd>ending {record.payment.card_last4}</dd></div>
                  <div><dt>Description</dt><dd>{record.payment.description}</dd></div>
                </dl>
              ) : (
                <Missing>{`No payment record for ${record.payment_reference}.`}</Missing>
              )}
            </PanelSection>
            <PanelSection title="Customer">
              {record.customer ? (
                <dl className="detail-fields compact">
                  <div>
                    <dt>KYC case</dt>
                    <dd>
                      <a href={`#kyc/${encodeURIComponent(record.customer.kyc_case_id)}`}>
                        {record.customer.customer_name} ({record.customer.kyc_case_id})
                      </a>
                    </dd>
                  </div>
                  <div><dt>KYC status · risk</dt><dd>{humanize(record.customer.kyc_status)} · {record.customer.risk_label}</dd></div>
                  <div><dt>Identity check</dt><dd>{record.customer.check_summary}</dd></div>
                </dl>
              ) : (
                <Missing>No linked KYC customer.</Missing>
              )}
            </PanelSection>
            <PanelSection title="Refund history">
              {record.refunds.length === 0 ? (
                <p className="muted">No refund exceptions recorded for {record.payment_reference}.</p>
              ) : (
                <ul className="linked-list">
                  {record.refunds.map((refund) => (
                    <li key={refund.id}>
                      <a href={`#refunds/${encodeURIComponent(refund.id)}`}>{refund.id}</a>{" "}
                      {formatMinorUnits(refund.amount_minor, refund.currency)} <StatusBadge status={refund.status} />
                      <div className="muted">
                        {refund.failure_reason} · {formatTimestamp(refund.created_at)}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </PanelSection>
            <PanelSection title="Evidence checklist">
              <EvidenceChecklist record={record} editable={editable} onUpdated={handleUpdated} />
            </PanelSection>
            <PanelSection title="Case notes">
              <CaseNotes key={`${record.id}-${record.notes_updated_at ?? ""}`} record={record} editable={editable} onUpdated={handleUpdated} />
            </PanelSection>
            <PanelSection title="Attachments">
              <Attachments record={record} editable={editable} onUpdated={handleUpdated} />
            </PanelSection>
            <PanelSection title="Evidence summary">
              <p className="muted">
                Internal PDF of case details, payment and refund history, notes and an attachment inventory. It is not a
                complete submission package: file contents are not included and nothing is submitted.
              </p>
              <a className="button-link" href={`/api/chargebacks/${encodeURIComponent(record.id)}/summary.pdf`}>
                Download evidence summary (PDF)
              </a>
            </PanelSection>
            <PanelSection title="Workflow">
              <ChargebackDecisionForm
                key={`${record.id}-${record.status}`}
                allowedActions={record.allowed_actions}
                canMutate={user.can_mutate}
                onSubmit={submitDecision}
              />
            </PanelSection>
            <PanelSection title="Activity history">
              <ActivityList recordType="chargeback" recordId={record.id} refreshKey={refreshKey} />
            </PanelSection>
          </DetailPanel>
        ) : (
          <DetailPanelPlaceholder error={detail.error} />
        ))}
    </div>
  );
}
