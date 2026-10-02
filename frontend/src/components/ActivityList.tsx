import { useEffect, useState } from "react";
import { api, queryString, type ActivityEntry } from "../api";
import { formatTimestamp, humanize } from "../format";

type Props = { recordType: string; recordId: string; refreshKey: number };

function show(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return formatTimestamp(value);
  return String(value);
}

/** "field: before → after" for each changed value recorded on an entry. */
export function formatChange(entry: ActivityEntry): string {
  const parts: string[] = [];
  if (entry.previous_status !== entry.new_status && entry.new_status) {
    parts.push(`${entry.previous_status ? humanize(entry.previous_status) : "—"} → ${humanize(entry.new_status)}`);
  }
  const before = entry.before_values ?? {};
  const after = entry.after_values ?? {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    if (before[key] === after[key]) continue;
    parts.push(`${humanize(key)}: ${show(before[key])} → ${show(after[key])}`);
  }
  return parts.join("; ");
}

/** Per-case history: case changes and work-management events (views/downloads are in the Audit Log). */
export function ActivityList({ recordType, recordId, refreshKey }: Props) {
  const [entries, setEntries] = useState<ActivityEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api<ActivityEntry[]>(
      `/api/activity${queryString({ record_type: recordType, record_id: recordId, category: ["case", "work"] })}`,
    )
      .then((data) => !cancelled && setEntries(data))
      .catch((err: Error) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [recordType, recordId, refreshKey]);

  if (error) return <div className="state state-error" role="alert">{error}</div>;
  if (entries === null) return <div className="state">Loading history…</div>;
  if (entries.length === 0) return <div className="state">No activity yet.</div>;

  return (
    <ol className="activity-list">
      {entries.map((entry) => {
        const change = formatChange(entry);
        return (
          <li key={entry.id} className={entry.category === "work" ? "activity-work" : undefined}>
            <div>
              <strong>{humanize(entry.action)}</strong> by {entry.actor_name}
              {change && <span className="muted"> · {change}</span>}
            </div>
            {entry.note && <div className="activity-note">{entry.note}</div>}
            <time className="muted" dateTime={entry.created_at}>
              {formatTimestamp(entry.created_at)}
            </time>
            {(entry.task_id !== null || entry.approval_id !== null) && (
              <span className="muted">
                {entry.task_id !== null && ` · task ${entry.task_id}`}
                {entry.approval_id !== null && ` · approval #${entry.approval_id}`}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
