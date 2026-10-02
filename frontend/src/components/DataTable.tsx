import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  selectedKey?: string | null;
  onSelect?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
  loading?: boolean;
  error?: string | null;
  emptyMessage?: string;
};

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  selectedKey,
  onSelect,
  rowClassName,
  loading = false,
  error = null,
  emptyMessage = "No records match these filters.",
}: Props<T>) {
  if (error) return <div className="state state-error" role="alert">{error}</div>;
  if (loading && rows.length === 0) return <div className="state">Loading…</div>;
  if (rows.length === 0) return <div className="state">{emptyMessage}</div>;

  return (
    <table className="data-table" aria-busy={loading}>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key}>{column.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const key = rowKey(row);
          return (
            <tr
              key={key}
              className={[key === selectedKey ? "selected" : "", rowClassName?.(row) ?? ""].join(" ").trim() || undefined}
              onClick={onSelect ? () => onSelect(row) : undefined}
              tabIndex={onSelect ? 0 : undefined}
              onKeyDown={
                onSelect
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") onSelect(row);
                    }
                  : undefined
              }
            >
              {columns.map((column) => (
                <td key={column.key}>{column.render(row)}</td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
