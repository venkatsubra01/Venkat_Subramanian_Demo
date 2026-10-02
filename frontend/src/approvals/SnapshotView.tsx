import { formatBytes } from "../chargebacks/types";
import { humanize } from "../format";
import type { EvidenceSnapshot } from "./types";

/** What an approval request covered, as captured when it was requested (metadata only, no file contents). */
export function SnapshotView({ snapshot }: { snapshot: EvidenceSnapshot }) {
  return (
    <div className="snapshot">
      <div className="muted">
        Evidence v{snapshot.evidence_version} · case status at request: {humanize(snapshot.status)}
      </div>
      <ul className="checklist">
        {snapshot.checklist.map((item) => (
          <li key={item.item_key}>
            {item.done ? "☑" : "☐"} {item.label}
          </li>
        ))}
      </ul>
      <div className="activity-note">{snapshot.notes || <span className="muted">(no notes)</span>}</div>
      {snapshot.attachments.length === 0 ? (
        <p className="muted">No attachments.</p>
      ) : (
        <ul className="attachment-list">
          {snapshot.attachments.map((a) => (
            <li key={a.id}>
              {a.filename} <span className="muted">({a.content_type}, {formatBytes(a.size_bytes)}, sha256 {a.sha256.slice(0, 12)}…)</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
