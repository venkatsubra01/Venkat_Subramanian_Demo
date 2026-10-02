import { useState, type FormEvent } from "react";
import { humanize } from "../format";
import { CLOSING_OUTCOMES } from "./types";

type Props = {
  allowedActions: string[];
  canMutate: boolean;
  onSubmit: (action: string, outcome: string | null, note: string) => Promise<void>;
};

/** Workflow step form; closing requires an outcome. */
export function ChargebackDecisionForm({ allowedActions, canMutate, onSubmit }: Props) {
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const action = allowedActions[0];
  if (!action) {
    return <div className="state">No further actions: this case is closed.</div>;
  }
  const closing = action === "close";

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (closing && !outcome) {
      setError("Choose a closing outcome.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(action, closing ? outcome : null, note);
      setNote("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="decision-form" onSubmit={handleSubmit}>
      {!canMutate && <p className="notice">Read-only: the viewer identity cannot change this case.</p>}
      <fieldset disabled={!canMutate || submitting}>
        {closing && (
          <label className="note-field">
            Closing outcome (required)
            <select value={outcome} onChange={(event) => setOutcome(event.target.value)} aria-label="Closing outcome">
              <option value="">Choose outcome…</option>
              {CLOSING_OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {humanize(o)}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="note-field">
          Note (optional)
          <textarea value={note} maxLength={1000} rows={2} onChange={(event) => setNote(event.target.value)} />
        </label>
        {error && <div className="state state-error" role="alert">{error}</div>}
        <button type="submit">{submitting ? "Saving…" : `Submit: ${humanize(action)}`}</button>
      </fieldset>
    </form>
  );
}
