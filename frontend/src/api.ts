export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type ValidationIssue = { loc?: (string | number)[]; msg?: string };

function describeDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((issue: ValidationIssue) => (issue.msg ?? "Invalid value").replace(/^Value error, /, ""))
      .join(" ");
  }
  return fallback;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : null;
    throw new ApiError(response.status, `${response.status}: ${describeDetail(detail, response.statusText)}`);
  }
  return data as T;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const response = await fetch(path, {
    method: init.method ?? "GET",
    credentials: "same-origin",
    headers: init.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  return parseResponse<T>(response);
}

/** POST a file as the raw request body; the server reads its type from Content-Type. */
export async function uploadFile<T>(path: string, file: File): Promise<T> {
  const response = await fetch(`${path}${queryString({ filename: file.name })}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  return parseResponse<T>(response);
}

export function queryString(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export type Identity = { id: string; name: string; role: string; can_mutate: boolean };

export type ActivityEntry = {
  id: number;
  record_type: string;
  record_id: string;
  actor_id: string;
  actor_name: string;
  action: string;
  previous_status: string | null;
  new_status: string | null;
  note: string | null;
  created_at: string;
};
