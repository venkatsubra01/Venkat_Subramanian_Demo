export type SourceApp = "kyc" | "refund" | "chargeback";
export const SOURCE_APPS: { id: SourceApp; label: string }[] = [
  { id: "kyc", label: "KYC review" },
  { id: "refund", label: "Refund exception" },
  { id: "chargeback", label: "Chargeback" },
];
export const PRIORITIES = ["urgent", "high", "normal", "low"] as const;
export const WORK_POLL_MS = 10_000;

export type WorkTask = {
  id: number;
  source_app: SourceApp;
  source_id: string;
  source_label: string;
  source_status: string;
  kind: string;
  state: "active" | "completed";
  assignee_id: string | null;
  assignee_name: string | null;
  priority: (typeof PRIORITIES)[number];
  due_at: string | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type TaskList = { items: WorkTask[]; total: number; overdue_count: number; unassigned_count: number };
export type Assignee = { id: string; name: string; role: string };

export function appLabel(app: string): string {
  return SOURCE_APPS.find((a) => a.id === app)?.label ?? app;
}

/** `datetime-local` input value (local time) <-> ISO UTC string. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}
