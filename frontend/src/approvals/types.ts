export type EvidenceSnapshot = {
  evidence_version: number;
  status: string;
  notes: string;
  checklist: { item_key: string; label: string; done: boolean }[];
  attachments: { id: string; filename: string; content_type: string; size_bytes: number; sha256: string }[];
};

export type ApprovalState = "pending" | "approved" | "returned" | "invalidated";

export type Approval = {
  id: number;
  source_app: string;
  source_id: string;
  kind: string;
  evidence_version: number;
  snapshot: EvidenceSnapshot;
  state: ApprovalState;
  requested_by_id: string;
  requested_by_name: string;
  requested_at: string;
  decided_by_id: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  invalidated_at: string | null;
  invalidated_reason: string | null;
};

export type ApprovalInboxItem = Approval & { source_label: string; source_status: string };
export type ApprovalInbox = { items: ApprovalInboxItem[]; state_counts: Record<ApprovalState, number> };
