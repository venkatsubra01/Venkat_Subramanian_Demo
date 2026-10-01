import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { RefundEventResult, RefundFailedEvent } from "./types";

function fictionalEvent(): RefundFailedEvent {
  const suffix = Math.random().toString(36).slice(2, 8);
  return {
    event_id: `evt_demo_${suffix}`,
    payment_reference: `pay_demo_${suffix}`,
    amount_minor: 2599,
    currency: "USD",
    failure_reason: "Destination card account closed.",
  };
}

type Props = { onResult: (result: RefundEventResult) => void; onCancel: () => void };

export function SimulateRefundForm({ onResult, onCancel }: Props) {
  const [event, setEvent] = useState<RefundFailedEvent>(fictionalEvent);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function update<K extends keyof RefundFailedEvent>(key: K, value: RefundFailedEvent[K]) {
    setEvent((current) => ({ ...current, [key]: value }));
  }

  async function send(payload: RefundFailedEvent) {
    setSubmitting(true);
    setError(null);
    try {
      onResult(await api<RefundEventResult>("/api/demo/events/refund-failed", { method: "POST", body: payload }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(formEvent: FormEvent) {
    formEvent.preventDefault();
    void send(event);
  }

  return (
    <form className="simulate-form" onSubmit={handleSubmit}>
      <p className="muted">
        Sends a fictional <code>refund.failed</code> event to the local demo endpoint. Submitting the same event id
        again replays it.
      </p>
      <fieldset disabled={submitting}>
        <label>
          Event id
          <input value={event.event_id} onChange={(e) => update("event_id", e.target.value)} required />
        </label>
        <label>
          Payment reference
          <input value={event.payment_reference} onChange={(e) => update("payment_reference", e.target.value)} required />
        </label>
        <label>
          Amount (minor units)
          <input
            type="number"
            min={1}
            step={1}
            value={event.amount_minor}
            onChange={(e) => update("amount_minor", Number(e.target.value))}
            required
          />
        </label>
        <label>
          Currency
          <input value={event.currency} maxLength={3} onChange={(e) => update("currency", e.target.value.toUpperCase())} required />
        </label>
        <label className="wide">
          Failure reason
          <input value={event.failure_reason} onChange={(e) => update("failure_reason", e.target.value)} required />
        </label>
      </fieldset>
      {error && <div className="state state-error" role="alert">{error}</div>}
      <div className="form-actions">
        <button type="submit" disabled={submitting}>Send event</button>
        <button type="button" className="secondary" onClick={() => setEvent(fictionalEvent())} disabled={submitting}>
          New event id
        </button>
        <button type="button" className="secondary" onClick={onCancel}>Close</button>
      </div>
    </form>
  );
}
