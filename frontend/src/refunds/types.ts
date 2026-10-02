export type RefundStatus = "open" | "escalated" | "resolved";

export const REFUND_STATUSES: RefundStatus[] = ["open", "escalated", "resolved"];

export type RefundException = {
  id: string;
  external_event_id: string;
  payment_reference: string;
  amount_minor: number;
  currency: string;
  failure_reason: string;
  status: RefundStatus;
  created_at: string;
};

export type RefundDetail = RefundException & { allowed_actions: string[] };

export type RefundList = { items: RefundException[]; status_counts: Record<RefundStatus, number> };

export type RefundFailedEvent = {
  event_id: string;
  payment_reference: string;
  amount_minor: number;
  currency: string;
  failure_reason: string;
};

export type RefundEventResult = { created: boolean; exception: RefundDetail };

export function formatMinorUnits(amountMinor: number, currency: string): string {
  try {
    const formatter = new Intl.NumberFormat(undefined, { style: "currency", currency });
    const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2;
    return formatter.format(amountMinor / 10 ** digits);
  } catch {
    return `${amountMinor} ${currency} (minor units)`;
  }
}
