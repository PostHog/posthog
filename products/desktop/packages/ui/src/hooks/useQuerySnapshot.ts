import { useEffect } from "react";

const PREFIX = "posthog.query-snapshot.v1.";

const MAX_SNAPSHOTS = 12;
const snapshots = new Map<string, unknown>();

/**
 * Keep project content in memory so that it never reaches plaintext disk storage.
 * Query observers share references to avoid serialization during a render.
 */
export function readQuerySnapshot<T>(name: string): T | undefined {
  return snapshots.get(name) as T | undefined;
}

function writeQuerySnapshot(name: string, value: unknown): void {
  if (snapshots.get(name) === value) return;
  snapshots.delete(name);
  snapshots.set(name, value);
  if (snapshots.size > MAX_SNAPSHOTS) {
    const oldest = snapshots.keys().next().value;
    if (oldest !== undefined) snapshots.delete(oldest);
  }
}

/** Snapshots hold project data, so a sign-out must drop them. */
export function clearQuerySnapshots(): void {
  snapshots.clear();
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(PREFIX)) localStorage.removeItem(key);
    }
  } catch {
    // Storage can be unavailable when the host denies access.
  }
}

// Remove plaintext snapshots from older builds without reading project content.
clearQuerySnapshots();

/**
 * Wait for pagination to settle so that later visits start with the full result.
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
