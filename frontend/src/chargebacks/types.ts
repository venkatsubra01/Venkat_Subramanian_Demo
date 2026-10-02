import type { Approval } from "../approvals/types";
import type { RefundException } from "../refunds/types";

export type ChargebackStatus = "open" | "collecting_evidence" | "ready_for_review" | "ready_for_submission" | "closed";

export const CHARGEBACK_STATUSES: ChargebackStatus[] = [
  "open",
  "collecting_evidence",
  "ready_for_review",
  "ready_for_submission",
  "closed",
];

export const CLOSING_OUTCOMES = ["won", "lost", "accepted", "withdrawn"] as const;

/** Mirrors the backend's upload allowlist and limit; the API enforces them. */
export const ATTACHMENT_ACCEPT = ".pdf,.png,.jpg,.jpeg,.txt,application/pdf,image/png,image/jpeg,text/plain";
export const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;

export type Chargeback = {
  id: string;
  payment_reference: string;
  cardholder_name: string;
  amount_minor: number;
  currency: string;
  reason: string;
  evidence_due_at: string;
  status: ChargebackStatus;
  outcome: string | null;
  created_at: string;
  closed_at: string | null;
  is_overdue: boolean;
};

export type Payment = {
  reference: string;
  customer_kyc_id: string | null;
  amount_minor: number;
  currency: string;
  captured_at: string;
  card_last4: string;
  description: string;
};

export type CustomerSummary = {
  kyc_case_id: string;
  customer_name: string;
  risk_label: string;
  kyc_status: string;
  check_summary: string;
};

export type ChecklistItem = {
  item_key: string;
  label: string;
  done: boolean;
  updated_by: string | null;
  updated_at: string | null;
};

export type Attachment = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by: string;
  uploaded_at: string;
};

export type ChargebackDetail = Chargeback & {
  allowed_actions: string[];
  evidence_version: number;
  can_request_approval: boolean;
  approvals: Approval[];
  notes: string;
  notes_updated_by: string | null;
  notes_updated_at: string | null;
  payment: Payment | null;
  customer: CustomerSummary | null;
  refunds: RefundException[];
  checklist: ChecklistItem[];
  attachments: Attachment[];
  missing_information: string[];
};

export type ChargebackList = {
  items: Chargeback[];
  status_counts: Record<ChargebackStatus, number>;
  overdue_count: number;
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
