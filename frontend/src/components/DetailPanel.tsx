import type { ReactNode } from "react";

type Field = { label: string; value: ReactNode };

type Props = {
  title: ReactNode;
  subtitle?: ReactNode;
  fields: Field[];
  children?: ReactNode;
  onClose?: () => void;
};

export function DetailPanel({ title, subtitle, fields, children, onClose }: Props) {
  return (
    <aside className="detail-panel">
      <header className="detail-header">
        <div>
          <h2>{title}</h2>
          {subtitle && <div className="muted">{subtitle}</div>}
        </div>
        {onClose && (
          <button type="button" className="link-button" onClick={onClose} aria-label="Close details">
            ✕
          </button>
        )}
      </header>
      <dl className="detail-fields">
        {fields.map((field) => (
          <div key={field.label}>
            <dt>{field.label}</dt>
            <dd>{field.value}</dd>
          </div>
        ))}
      </dl>
      {children}
    </aside>
  );
}

export function PanelSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export function DetailPanelPlaceholder({ error }: { error: string | null }) {
  return (
    <aside className="detail-panel">
      {error ? (
        <div className="state state-error" role="alert">{error}</div>
      ) : (
        <div className="state">Loading details…</div>
      )}
    </aside>
  );
}
