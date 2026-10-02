export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}
