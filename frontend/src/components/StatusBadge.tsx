import { humanize } from "../format";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{humanize(status)}</span>;
}
