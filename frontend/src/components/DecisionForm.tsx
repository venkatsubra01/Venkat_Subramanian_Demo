import { useState, type FormEvent } from "react";
import { humanize } from "../format";

type Props = {
  allowedActions: string[];
  noteRequired: (action: string) => boolean;
  canMutate: boolean;
  onSubmit: (action: string, note: string) => Promise<void>;
};

export function DecisionForm({ allowedActions, noteRequired, canMutate, onSubmit }: Props) {
  const [action, setAction] = useState(allowedActions[0] ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (allowedActions.length === 0) {
    return <div className="state">No further actions: this record is in a terminal status.</div>;
  }

  const selected = allowedActions.includes(action) ? action : allowedActions[0];
  const required = noteRequired(selected);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (required && !note.trim()) {
      setError("A note is required for this action.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(selected, note);
      setNote("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="decision-form" onSubmit={handleSubmit}>
      {!canMutate && <p className="notice">Read-only: the viewer identity cannot make decisions.</p>}
      <fieldset disabled={!canMutate || submitting}>
        <div className="action-options">
          {allowedActions.map((option) => (
            <label key={option}>
              <input
                type="radio"
                name="action"
                value={option}
                checked={selected === option}
                onChange={() => setAction(option)}
              />
              {humanize(option)}
            </label>
          ))}
        </div>
        <label className="note-field">
          Note {required ? "(required)" : "(optional)"}
          <textarea value={note} maxLength={1000} rows={3} onChange={(event) => setNote(event.target.value)} />
        </label>
        {error && <div className="state state-error" role="alert">{error}</div>}
        <button type="submit">{submitting ? "Saving…" : `Submit: ${humanize(selected)}`}</button>
      </fieldset>
    </form>
  );
}
