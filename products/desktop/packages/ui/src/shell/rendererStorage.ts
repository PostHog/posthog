import { createJSONStorage, type StateStorage } from "zustand/middleware";
import { logger } from "./logger";

export type RendererStateStorage = StateStorage;

const log = logger.scope("renderer-storage");

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

let hostStorage: RendererStateStorage | null = null;
const hostStorageReady = deferred<RendererStateStorage>();

// Re-registration replaces `hostStorage` for new calls, while the promise
// keeps settling waiters against the first registration.
const resolveHostStorage = () => hostStorage ?? hostStorageReady.promise;

const pendingFirstReads = new Set<string>();
const settledFirstReads = new Set<string>();

// Writes are coalesced per key before they reach the host: persisted stores
// (drafts in particular) can update on every keystroke, and on desktop each
// write is an IPC hop plus an encrypt-and-rewrite of the whole store file on
// the main process. Only the latest value per key matters, so bursts fold
// into one write after WRITE_DEBOUNCE_MS of quiet, with WRITE_MAX_WAIT_MS
// bounding how stale the persisted copy can get during sustained typing.
export const WRITE_DEBOUNCE_MS = 1_000;
export const WRITE_MAX_WAIT_MS = 5_000;

interface PendingWrite {
  value: string;
  firstQueuedAt: number;
  timer: ReturnType<typeof setTimeout>;
}

const pendingWrites = new Map<string, PendingWrite>();

/** Detach and return the pending write for a key, cancelling its timer. */
function takePendingWrite(key: string): PendingWrite | undefined {
  const pending = pendingWrites.get(key);
  if (pending) {
    clearTimeout(pending.timer);
    pendingWrites.delete(key);
  }
  return pending;
}

async function flushPendingWrite(key: string): Promise<void> {
  // Detach before awaiting so a write landing mid-flush queues a fresh entry
  // instead of mutating one that is already on its way out.
  const pending = takePendingWrite(key);
  if (!pending) {
    return;
  }
  try {
    const storage = await resolveHostStorage();
    await storage.setItem(key, pending.value);
  } catch (error) {
    // zustand persist fires writes without awaiting them; a rejection here
    // would only surface as an unhandled rejection.
    log.error("Failed to persist state", { key, error });
  }
}

function queuePendingWrite(key: string, value: string): void {
  const existing = pendingWrites.get(key);
  if (existing) {
    clearTimeout(existing.timer);
  }
  const firstQueuedAt = existing?.firstQueuedAt ?? Date.now();
  const delay = Math.max(
    0,
    Math.min(WRITE_DEBOUNCE_MS, firstQueuedAt + WRITE_MAX_WAIT_MS - Date.now()),
  );
  pendingWrites.set(key, {
    value,
    firstQueuedAt,
    timer: setTimeout(() => void flushPendingWrite(key), delay),
  });
}

/**
 * Push every coalesced write to the host immediately. Wired to `pagehide` as
 * a best-effort flush so pending state (e.g. a draft mid-keystroke) lands
 * before the window goes away; hosts with an explicit shutdown seam can
 * await it for a guaranteed flush.
 */
export async function flushRendererStateWrites(): Promise<void> {
  await Promise.all(
    Array.from(pendingWrites.keys(), (key) => flushPendingWrite(key)),
  );
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => void flushRendererStateWrites());
}

/**
 * Hosts call this during boot with their persistence backend. Persisted UI
 * stores are created at module-evaluation time, which can run before the host
 * composition root has finished, so reads and writes issued before
 * registration wait for the backend instead of treating "not registered yet"
 * as "no saved data". That fallback hydrated every store with defaults and
 * the next write then overwrote the persisted state with those defaults.
 *
 * Registering again replaces the backend for new calls; waiters already in
 * flight settle against the first registration.
 */
export function registerRendererStateStorage(
  storage: RendererStateStorage,
): void {
  hostStorage = storage;
  hostStorageReady.resolve(storage);
}

const deferredHostStorage: StateStorage = {
  getItem: async (key) => {
    // A coalesced write that has not flushed yet is newer than the backend
    // copy; land it first so the read never observes older state. A queued
    // write also means the key is past hydration, so the first-read
    // bookkeeping below (which must run synchronously to catch racing
    // writes) does not apply.
    const hadPendingWrite = pendingWrites.has(key);
    if (hadPendingWrite) {
      await flushPendingWrite(key);
    }
    const isFirstRead =
      !hadPendingWrite &&
      !settledFirstReads.has(key) &&
      !pendingFirstReads.has(key);
    if (isFirstRead) {
      pendingFirstReads.add(key);
    }
    try {
      const storage = await resolveHostStorage();
      return await storage.getItem(key);
    } finally {
      if (isFirstRead) {
        pendingFirstReads.delete(key);
        settledFirstReads.add(key);
      }
    }
  },
  setItem: async (key, value) => {
    // A write racing the initial read serializes pre-hydration (default)
    // state, and hydration replaces in-memory state for persisted keys right
    // after. The snapshot is stale either way, so drop it instead of letting
    // it overwrite the values the read is about to return.
    if (pendingFirstReads.has(key)) {
      return;
    }
    queuePendingWrite(key, value);
  },
  removeItem: async (key) => {
    // Removal is explicit intent rather than a stale state snapshot, so it is
    // not dropped while the initial read is in flight. A coalesced write for
    // the key is cancelled so it cannot resurrect the state afterwards.
    takePendingWrite(key);
    try {
      const storage = await resolveHostStorage();
      await storage.removeItem(key);
    } catch (error) {
      log.error("Failed to remove persisted state", { key, error });
    }
  },
};

export const electronStorage = createJSONStorage(() => deferredHostStorage);
