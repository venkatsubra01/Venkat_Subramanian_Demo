import { useApi } from "../useApi";
import { formatTimestamp } from "../format";
import { WORK_POLL_MS, type WorkTask } from "../work/types";

/** Read-only summary of the Work Manager task for a source case. */
export function CaseTask({ app, id, refreshKey }: { app: string; id: string; refreshKey: number }) {
  const task = useApi<WorkTask | null>(
    `/api/work/by-source/${app}/${encodeURIComponent(id)}`,
    refreshKey,
    0,
    WORK_POLL_MS,
  );
  if (task.error) return <div className="state state-error" role="alert">{task.error}</div>;
  if (task.loading && task.data === null) return <div className="state">Loading task…</div>;
  if (!task.data) return <p className="muted">No task: this case is not actionable.</p>;
  const t = task.data;
  return (
    <p className="case-task">
      Task {t.id} · <strong>{t.state}</strong> · {t.assignee_name ?? "unassigned"} ·{" "}
      <span className={`priority priority-${t.priority}`}>{t.priority}</span>
      {t.due_at && (
        <span className={t.is_overdue ? "overdue" : undefined}>
          {" "}
          · due {formatTimestamp(t.due_at)}
          {t.is_overdue && <span className="overdue-tag">Overdue</span>}
        </span>
      )}
    </p>
  );
}
