import { useCallback, useEffect, useRef, useState } from "react";
import { MissingKeyError } from "./api";

/** Fetch + poll. Polling continues while `active` (default true). */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 3000, active = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      setData(await fetcherRef.current());
      setError(null);
    } catch (e) {
      setError(e as Error);
    }
  }, []);

  useEffect(() => {
    refresh();
    if (!active) return;
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs, active]);

  return { data, error, refresh };
}

export function missingKeyMessage(error: Error | null): string | null {
  if (error instanceof MissingKeyError) return error.message;
  return null;
}
