import { logger } from "@posthog/ui/shell/logger";

const log = logger.scope("terminal-scrollback");

export interface ScrollbackBackend {
  loadAll(): Promise<Record<string, string>>;
  save(key: string, value: string): Promise<void>;
  remove(keys: string[]): Promise<void>;
  clear(): Promise<void>;
}

export const TERMINAL_SCROLLBACK_LINES = 1000;
export const SERIALIZE_SCROLLBACK_LINES = 400;

const MAX_ENTRY_BYTES = 128 * 1024;
const MAX_ENTRIES = 32;
const FLUSH_INTERVAL_MS = 3000;
const LEGACY_STORE_KEY = "terminal-store";
const ACTION_KEY_PREFIX = "action-";

const DB_NAME = "posthog-terminal";
const DB_VERSION = 1;
const STORE_NAME = "scrollback";

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("IndexedDB open blocked"));
  });
}

export function createIndexedDbScrollbackBackend(): ScrollbackBackend {
  let dbPromise: Promise<IDBDatabase> | null = null;

  const getDb = (): Promise<IDBDatabase> => {
    if (!dbPromise) {
      dbPromise = openDatabase().catch((error) => {
        dbPromise = null;
        throw error;
      });
    }
    return dbPromise;
  };

  const withStore = async <T>(
    mode: IDBTransactionMode,
    run: (store: IDBObjectStore) => Promise<T>,
  ): Promise<T> => {
    const db = await getDb();
    const transaction = db.transaction(STORE_NAME, mode);
    const result = await run(transaction.objectStore(STORE_NAME));
    await new Promise<void>((resolve, reject) => {
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
    return result;
  };

  return {
    async loadAll() {
      try {
        return await withStore("readonly", async (store) => {
          const [keys, values] = await Promise.all([
            requestToPromise(store.getAllKeys()),
            requestToPromise(store.getAll()),
          ]);
          const entries: Record<string, string> = {};
          keys.forEach((key, index) => {
            const value = values[index];
            if (typeof key === "string" && typeof value === "string") {
              entries[key] = value;
            }
          });
          return entries;
        });
      } catch (error) {
        log.error("Failed to load scrollback", error);
        return {};
      }
    },

    async save(key, value) {
      try {
        await withStore("readwrite", async (store) => {
          store.put(value, key);
        });
      } catch (error) {
        log.error("Failed to save scrollback", { key, error });
      }
    },

    async remove(keys) {
      if (keys.length === 0) return;
      try {
        await withStore("readwrite", async (store) => {
          for (const key of keys) {
            store.delete(key);
          }
        });
      } catch (error) {
        log.error("Failed to remove scrollback", error);
      }
    },

    async clear() {
      try {
        await withStore("readwrite", async (store) => {
          store.clear();
        });
      } catch (error) {
        log.error("Failed to clear scrollback", error);
      }
    },
  };
}

let backend: ScrollbackBackend = createIndexedDbScrollbackBackend();
let cache = new Map<string, string>();
const dirty = new Set<string>();
let flushHandle: ReturnType<typeof setTimeout> | null = null;
let hydrated: Promise<void> | null = null;
let hydrationComplete = false;

export function registerScrollbackBackend(next: ScrollbackBackend): void {
  backend = next;
  cache = new Map();
  dirty.clear();
  hydrated = null;
  hydrationComplete = false;
  if (flushHandle !== null) {
    clearTimeout(flushHandle);
    flushHandle = null;
  }
}

// Hosts that never hydrate simply run without persistence, so an unstarted
// hydration must not block terminals from writing.
export function isScrollbackReady(): boolean {
  return hydrated === null || hydrationComplete;
}

export function whenScrollbackReady(): Promise<void> {
  return hydrated ?? Promise.resolve();
}

function isTaskKey(key: string, taskId: string): boolean {
  return key === taskId || key.startsWith(`${taskId}-`);
}

function evictOverflow(): string[] {
  const overflow = cache.size - MAX_ENTRIES;
  if (overflow <= 0) return [];

  const evicted: string[] = [];
  for (const key of cache.keys()) {
    if (evicted.length >= overflow) break;
    evicted.push(key);
  }
  for (const key of evicted) {
    cache.delete(key);
    dirty.delete(key);
  }
  return evicted;
}

export async function flushScrollback(): Promise<void> {
  if (flushHandle !== null) {
    clearTimeout(flushHandle);
    flushHandle = null;
  }

  const pending = [...dirty];
  dirty.clear();

  const evicted = evictOverflow();
  const writes = pending
    .filter((key) => cache.has(key))
    .map((key) => backend.save(key, cache.get(key) as string));

  try {
    await Promise.all(writes);
    if (evicted.length > 0) {
      await backend.remove(evicted);
    }
  } catch (error) {
    log.error("Failed to flush scrollback", error);
  }
}

function scheduleFlush(): void {
  if (flushHandle !== null) return;
  flushHandle = setTimeout(() => {
    flushHandle = null;
    void flushScrollback();
  }, FLUSH_INTERVAL_MS);
}

export function getScrollback(key: string): string | undefined {
  const value = cache.get(key);
  if (value === undefined) return undefined;
  cache.delete(key);
  cache.set(key, value);
  return value;
}

export function setScrollback(key: string, value: string): void {
  const bounded =
    value.length > MAX_ENTRY_BYTES ? value.slice(-MAX_ENTRY_BYTES) : value;
  cache.delete(key);
  cache.set(key, bounded);
  dirty.add(key);
  scheduleFlush();
}

export function removeScrollback(key: string): void {
  cache.delete(key);
  dirty.delete(key);
  void backend.remove([key]);
}

export function removeScrollbackForTask(taskId: string): void {
  const keys = [...cache.keys()].filter((key) => isTaskKey(key, taskId));
  if (keys.length === 0) return;
  for (const key of keys) {
    cache.delete(key);
    dirty.delete(key);
  }
  void backend.remove(keys);
}

export function clearScrollback(): Promise<void> {
  cache.clear();
  dirty.clear();
  if (flushHandle !== null) {
    clearTimeout(flushHandle);
    flushHandle = null;
  }
  return backend.clear();
}

function migrateLegacyTerminalStore(): void {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(LEGACY_STORE_KEY);
  } catch (error) {
    log.error("Failed to read legacy terminal store", error);
    return;
  }
  if (!raw) return;

  try {
    const parsed = JSON.parse(raw) as {
      state?: {
        terminalStates?: Record<string, { serializedState?: unknown }>;
      };
    };
    const states = parsed.state?.terminalStates ?? {};

    for (const [key, value] of Object.entries(states)) {
      if (key.startsWith(ACTION_KEY_PREFIX)) continue;
      if (cache.has(key)) continue;
      if (typeof value?.serializedState !== "string") continue;
      setScrollback(key, value.serializedState);
    }
  } catch (error) {
    log.error("Failed to migrate legacy terminal store", error);
  }

  try {
    localStorage.removeItem(LEGACY_STORE_KEY);
  } catch (error) {
    log.error("Failed to remove legacy terminal store", error);
  }
}

export function hydrateTerminalScrollback(): Promise<void> {
  if (hydrated) return hydrated;

  // The flush is throttled, so a quit inside the window would drop the most
  // recent scrollback without this.
  window.addEventListener("pagehide", () => {
    void flushScrollback();
  });

  hydrated = (async () => {
    const entries = await backend.loadAll();
    for (const [key, value] of Object.entries(entries)) {
      if (!cache.has(key)) {
        cache.set(key, value);
      }
    }
    migrateLegacyTerminalStore();

    const evicted = evictOverflow();
    if (evicted.length > 0) {
      await backend.remove(evicted);
    }
  })()
    .catch((error) => {
      log.error("Failed to hydrate scrollback", error);
    })
    .finally(() => {
      hydrationComplete = true;
    });

  return hydrated;
}
