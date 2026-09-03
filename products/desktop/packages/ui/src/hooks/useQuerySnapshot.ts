import { useEffect } from "react";

const PREFIX = "posthog.query-snapshot.v1.";

/** A snapshot must beat a round trip. One this large no longer would. */
const MAX_CHARS = 2_000_000;

/**
 * The answer a query gave last time, kept on disk. A page seeds its query with
 * it to paint content on the first frame, then refreshes behind that content.
 * The snapshot is an optimization: every failure path here is silent.
 */
export function readQuerySnapshot<T>(name: string): T | undefined {
  try {
    const raw = localStorage.getItem(PREFIX + name);
    return raw === null ? undefined : (JSON.parse(raw) as T);
  } catch {
    return undefined;
  }
}

function writeQuerySnapshot(name: string, value: unknown): void {
  try {
    const raw = JSON.stringify(value);
    if (raw.length > MAX_CHARS) {
      localStorage.removeItem(PREFIX + name);
      return;
    }
    localStorage.setItem(PREFIX + name, raw);
  } catch {
    // Quota and serialization failures cost the next paint, nothing more.
  }
}

/** Snapshots hold project data, so a sign-out must drop them. */
export function clearQuerySnapshots(): void {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(PREFIX)) localStorage.removeItem(key);
    }
  } catch {
    // Same as above: losing a snapshot only costs a paint.
  }
}

/**
 * Writes the snapshot when the query settles. Waiting for `settled` keeps a
 * paginated fetch from writing the whole document once per page.
 */
export function useWriteQuerySnapshot(
  name: string,
  data: unknown,
  settled: boolean,
): void {
  useEffect(() => {
    if (!settled || data === undefined) return;
    writeQuerySnapshot(name, data);
  }, [name, data, settled]);
}
