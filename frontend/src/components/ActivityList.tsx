import { useEffect, useState } from "react";
import { api, queryString, type ActivityEntry } from "../api";
import { formatTimestamp, humanize } from "../format";

type Props = { recordType: string; recordId: string; refreshKey: number };

export function ActivityList({ recordType, recordId, refreshKey }: Props) {
  const [entries, setEntries] = useState<ActivityEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api<ActivityEntry[]>(`/api/activity${queryString({ record_type: recordType, record_id: recordId })}`)
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
      {entries.map((entry) => (
        <li key={entry.id}>
          <div>
            <strong>{humanize(entry.action)}</strong> by {entry.actor_name}
            {entry.previous_status !== entry.new_status && entry.new_status && (
              <span className="muted">
                {" "}
                · {entry.previous_status ? humanize(entry.previous_status) : "—"} → {humanize(entry.new_status)}
              </span>
            )}
          </div>
          {entry.note && <div className="activity-note">{entry.note}</div>}
          <time className="muted" dateTime={entry.created_at}>
            {formatTimestamp(entry.created_at)}
          </time>
        </li>
      ))}
    </ol>
  );
}
