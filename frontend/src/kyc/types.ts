export type KycStatus = "pending_review" | "awaiting_information" | "approved" | "rejected";

export const KYC_STATUSES: KycStatus[] = ["pending_review", "awaiting_information", "approved", "rejected"];

export const RISK_LABELS = ["low", "medium", "high"] as const;

export type KycCase = {
  id: string;
  customer_name: string;
  submitted_at: string;
  risk_label: string;
  check_summary: string;
  status: KycStatus;
};

export type KycCaseDetail = KycCase & { allowed_actions: string[] };

export type KycList = { items: KycCase[]; status_counts: Record<KycStatus, number> };

export const KYC_NOTE_REQUIRED = new Set(["reject", "request_information", "return_to_review"]);
