import { useState, type ChangeEvent } from "react";
import { api, uploadFile } from "../api";
import { formatTimestamp } from "../format";
import {
  ATTACHMENT_ACCEPT,
  formatBytes,
  MAX_ATTACHMENT_BYTES,
  type ChargebackDetail,
} from "./types";

type SectionProps = {
  record: ChargebackDetail;
  editable: boolean;
  onUpdated: (updated: ChargebackDetail) => void;
};

function casePath(record: ChargebackDetail): string {
  return `/api/chargebacks/${encodeURIComponent(record.id)}`;
}

export function EvidenceChecklist({ record, editable, onUpdated }: SectionProps) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  async function toggle(itemKey: string, done: boolean) {
    setSaving(itemKey);
    setError(null);
    try {
      onUpdated(
        await api<ChargebackDetail>(`${casePath(record)}/checklist/${encodeURIComponent(itemKey)}`, {
          method: "PUT",
          body: { done },
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(null);
    }
  }

  const done = record.checklist.filter((item) => item.done).length;
  return (
    <>
      <p className="muted">
        {done} of {record.checklist.length} collected. Items are demo assumptions for a “{record.reason.replace(/_/g, " ")}” dispute.
      </p>
      <ul className="checklist">
        {record.checklist.map((item) => (
          <li key={item.item_key}>
            <label>
              <input
                type="checkbox"
                checked={item.done}
                disabled={!editable || saving !== null}
                onChange={(event) => toggle(item.item_key, event.target.checked)}
              />
              <span>{item.label}</span>
            </label>
            {item.done && item.updated_by && (
              <span className="muted">
                {item.updated_by}
                {item.updated_at ? `, ${formatTimestamp(item.updated_at)}` : ""}
              </span>
            )}
          </li>
        ))}
      </ul>
      {error && <div className="state state-error" role="alert">{error}</div>}
    </>
  );
}

export function CaseNotes({ record, editable, onUpdated }: SectionProps) {
  const [draft, setDraft] = useState(record.notes);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const dirty = draft.trim() !== record.notes;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api<ChargebackDetail>(`${casePath(record)}/notes`, { method: "PUT", body: { notes: draft } });
      setDraft(updated.notes);
      onUpdated(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="case-notes">
      <textarea
        value={draft}
        rows={4}
        maxLength={5000}
        readOnly={!editable}
        placeholder={editable ? "Add case notes…" : "No case notes."}
        onChange={(event) => setDraft(event.target.value)}
        aria-label="Case notes"
      />
      {record.notes_updated_by && record.notes_updated_at && (
        <span className="muted">
          Last saved by {record.notes_updated_by}, {formatTimestamp(record.notes_updated_at)}
        </span>
      )}
      {error && <div className="state state-error" role="alert">{error}</div>}
      {editable && (
        <div className="form-actions">
          <button type="button" onClick={save} disabled={!dirty || saving}>
            {saving ? "Saving…" : "Save notes"}
          </button>
          {dirty && (
            <button type="button" className="secondary" onClick={() => setDraft(record.notes)} disabled={saving}>
              Discard
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function Attachments({ record, editable, onUpdated }: SectionProps) {
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    if (!file) return;
    setError(null);
    if (file.size > MAX_ATTACHMENT_BYTES) {
      setError(`${file.name} is larger than the 5 MB limit.`);
      input.value = "";
      return;
    }
    setUploading(true);
    try {
      onUpdated(await uploadFile<ChargebackDetail>(`${casePath(record)}/attachments`, file));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      input.value = "";
    }
  }

  return (
    <>
      {record.attachments.length === 0 ? (
        <p className="muted">No evidence files uploaded.</p>
      ) : (
        <ul className="attachment-list">
          {record.attachments.map((file) => (
            <li key={file.id}>
              <a href={`${casePath(record)}/attachments/${encodeURIComponent(file.id)}`} download={file.filename}>
                {file.filename}
              </a>
              <span className="muted">
                {formatBytes(file.size_bytes)} · {file.uploaded_by} · {formatTimestamp(file.uploaded_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <label className="upload-field">
          <span>{uploading ? "Uploading…" : "Upload evidence file"}</span>
          <input type="file" accept={ATTACHMENT_ACCEPT} onChange={handleFile} disabled={uploading} />
          <span className="muted">PDF, PNG, JPEG or plain text; up to 5 MB. Stored locally on this machine.</span>
        </label>
      )}
      {error && <div className="state state-error" role="alert">{error}</div>}
    </>
  );
}
