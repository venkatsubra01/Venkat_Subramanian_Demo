import { useEffect, useState } from "react";
import { api } from "./api";

/** Load `path` (GET) whenever it or `refreshKey` changes. `null` path skips loading. */
export function useApi<T>(path: string | null, refreshKey = 0, debounceMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);

  useEffect(() => {
    if (path === null) {
      setData(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      api<T>(path)
        .then((result) => {
          if (cancelled) return;
          setData(result);
          setError(null);
        })
        .catch((err: Error) => !cancelled && setError(err.message))
        .finally(() => !cancelled && setLoading(false));
    }, debounceMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [path, refreshKey, debounceMs]);

  return { data, error, loading, setData };
}
