import { useState } from "react";
import { api, type Identity } from "../api";
import { SnapshotView } from "../approvals/SnapshotView";
import { StatusBadge } from "../components/StatusBadge";
import { formatTimestamp } from "../format";
import type { ChargebackDetail } from "./types";

type Props = { record: ChargebackDetail; user: Identity; onUpdated: (updated: ChargebackDetail) => void };

export function EvidenceApproval({ record, user, onUpdated }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  async function requestApproval() {
    setSaving(true);
    setError(null);
    try {
      onUpdated(
        await api<ChargebackDetail>(`/api/chargebacks/${encodeURIComponent(record.id)}/approval-requests`, { method: "POST" }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <p className="muted">
        Current evidence version: <strong>v{record.evidence_version}</strong>. Changing the checklist, notes or attachments
        creates a new version and invalidates pending or granted approval. A different supervisor must approve the current
        version before the case becomes “ready for submission” (internal only).
      </p>
      {record.status === "ready_for_review" && user.can_mutate && (
        <button type="button" onClick={requestApproval} disabled={saving || !record.can_request_approval}>
          {record.can_request_approval ? `Request approval of v${record.evidence_version}` : "Approval pending"}
        </button>
      )}
      {error && <div className="state state-error" role="alert">{error}</div>}
      {record.approvals.length > 0 && (
        <ul className="linked-list approval-list">
          {record.approvals.map((a) => (
            <li key={a.id}>
              <div>
                Request #{a.id} · v{a.evidence_version} <StatusBadge status={a.state} />{" "}
                {a.evidence_version !== record.evidence_version && <span className="muted">(not current)</span>}
              </div>
              <div className="muted">
                Requested by {a.requested_by_name} · {formatTimestamp(a.requested_at)}
                {a.decided_by_name && ` · ${a.state} by ${a.decided_by_name}`}
              </div>
              {a.decision_reason && <div className="activity-note">{a.decision_reason}</div>}
              {a.invalidated_reason && <div className="activity-note">{a.invalidated_reason}</div>}
              <button type="button" className="link-button" onClick={() => setOpen(open === a.id ? null : a.id)}>
                {open === a.id ? "Hide submitted evidence" : "Show submitted evidence"}
              </button>
              {open === a.id && <SnapshotView snapshot={a.snapshot} />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
