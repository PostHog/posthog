import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { logError } = vi.hoisted(() => ({ logError: vi.fn() }));

vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({ info: vi.fn(), warn: vi.fn(), error: logError }),
  },
}));

import {
  clearScrollback,
  flushScrollback,
  getScrollback,
  hydrateTerminalScrollback,
  isScrollbackReady,
  registerScrollbackBackend,
  removeScrollback,
  removeScrollbackForTask,
  type ScrollbackBackend,
  setScrollback,
} from "./terminalScrollback";

const MAX_ENTRY_BYTES = 128 * 1024;
const MAX_ENTRIES = 32;
const FLUSH_INTERVAL_MS = 3000;

function createFakeBackend(initial: Record<string, string> = {}) {
  const entries = new Map(Object.entries(initial));
  return {
    entries,
    loadAll: vi.fn(async () => Object.fromEntries(entries)),
    save: vi.fn(async (key: string, value: string) => {
      entries.set(key, value);
    }),
    remove: vi.fn(async (keys: string[]) => {
      for (const key of keys) entries.delete(key);
    }),
    clear: vi.fn(async () => {
      entries.clear();
    }),
  } satisfies ScrollbackBackend & { entries: Map<string, string> };
}

let backend: ReturnType<typeof createFakeBackend>;

beforeEach(() => {
  vi.useFakeTimers();
  logError.mockClear();
  localStorage.clear();
  backend = createFakeBackend();
  registerScrollbackBackend(backend);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("setScrollback", () => {
  it("keeps the tail when a value exceeds the byte cap", async () => {
    const value = `${"a".repeat(MAX_ENTRY_BYTES)}TAIL`;

    setScrollback("key", value);

    expect(getScrollback("key")).toHaveLength(MAX_ENTRY_BYTES);
    expect(getScrollback("key")?.endsWith("TAIL")).toBe(true);

    await flushScrollback();
    expect(backend.entries.get("key")).toHaveLength(MAX_ENTRY_BYTES);
  });

  it("coalesces repeated writes within one flush window into a single save", async () => {
    setScrollback("key", "one");
    setScrollback("key", "two");
    setScrollback("key", "three");

    expect(backend.save).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS);

    expect(backend.save).toHaveBeenCalledTimes(1);
    expect(backend.save).toHaveBeenCalledWith("key", "three");
  });

  it("evicts least recently used entries past the cap", async () => {
    for (let i = 0; i < MAX_ENTRIES + 2; i++) {
      setScrollback(`key-${i}`, `value-${i}`);
    }

    await flushScrollback();

    expect(getScrollback("key-0")).toBeUndefined();
    expect(getScrollback("key-1")).toBeUndefined();
    expect(getScrollback("key-2")).toBe("value-2");
    expect(backend.remove).toHaveBeenCalledWith(["key-0", "key-1"]);
    expect(backend.entries.has("key-0")).toBe(false);
  });

  it("treats a read as a recency touch", async () => {
    for (let i = 0; i < MAX_ENTRIES; i++) {
      setScrollback(`key-${i}`, `value-${i}`);
    }
    getScrollback("key-0");
    setScrollback("key-new", "value-new");

    await flushScrollback();

    expect(getScrollback("key-0")).toBe("value-0");
    expect(getScrollback("key-1")).toBeUndefined();
  });

  it("swallows and logs a rejecting backend", async () => {
    backend.save.mockRejectedValueOnce(new Error("disk full"));

    setScrollback("key", "value");
    await expect(flushScrollback()).resolves.toBeUndefined();

    expect(logError).toHaveBeenCalled();
  });
});

describe("removal", () => {
  it("removes a single key from cache and backend", async () => {
    setScrollback("key", "value");
    await flushScrollback();

    removeScrollback("key");

    expect(getScrollback("key")).toBeUndefined();
    expect(backend.remove).toHaveBeenCalledWith(["key"]);
  });

  it("removes only keys belonging to the task", async () => {
    setScrollback("task-1", "a");
    setScrollback("task-1-shell", "b");
    setScrollback("task-10-shell", "c");
    setScrollback("task-2-shell", "d");
    await flushScrollback();

    removeScrollbackForTask("task-1");

    expect(getScrollback("task-1")).toBeUndefined();
    expect(getScrollback("task-1-shell")).toBeUndefined();
    expect(getScrollback("task-10-shell")).toBe("c");
    expect(getScrollback("task-2-shell")).toBe("d");
  });
});

describe("clearScrollback", () => {
  it("empties the cache and the backend", async () => {
    setScrollback("key", "value");
    await flushScrollback();

    await clearScrollback();

    expect(getScrollback("key")).toBeUndefined();
    expect(backend.clear).toHaveBeenCalled();
  });
});

describe("hydrateTerminalScrollback", () => {
  it("loads persisted entries and only reads the backend once", async () => {
    registerScrollbackBackend(createFakeBackend({ key: "restored" }));

    await hydrateTerminalScrollback();
    await hydrateTerminalScrollback();

    expect(getScrollback("key")).toBe("restored");
  });

  it("migrates the legacy localStorage store and removes it", async () => {
    localStorage.setItem(
      "terminal-store",
      JSON.stringify({
        state: {
          terminalStates: {
            "task-1-shell": { serializedState: "legacy", sessionId: null },
            "action-abc-0": { serializedState: "action-noise" },
            "task-2-shell": { serializedState: null },
          },
        },
      }),
    );

    await hydrateTerminalScrollback();

    expect(getScrollback("task-1-shell")).toBe("legacy");
    expect(getScrollback("action-abc-0")).toBeUndefined();
    expect(getScrollback("task-2-shell")).toBeUndefined();
    expect(localStorage.getItem("terminal-store")).toBeNull();
  });

  it("does not let the legacy store overwrite already-persisted entries", async () => {
    registerScrollbackBackend(createFakeBackend({ "task-1-shell": "current" }));
    localStorage.setItem(
      "terminal-store",
      JSON.stringify({
        state: {
          terminalStates: { "task-1-shell": { serializedState: "legacy" } },
        },
      }),
    );

    await hydrateTerminalScrollback();

    expect(getScrollback("task-1-shell")).toBe("current");
  });

  it("reports ready only once an in-flight hydration settles", async () => {
    let releaseLoad!: (entries: Record<string, string>) => void;
    const slow = createFakeBackend();
    slow.loadAll.mockReturnValue(
      new Promise((resolve) => {
        releaseLoad = resolve;
      }),
    );
    registerScrollbackBackend(slow);

    expect(isScrollbackReady()).toBe(true);

    const pending = hydrateTerminalScrollback();
    expect(isScrollbackReady()).toBe(false);

    releaseLoad({ key: "restored" });
    await pending;

    expect(isScrollbackReady()).toBe(true);
    expect(getScrollback("key")).toBe("restored");
  });

  it("reports ready even when hydration fails", async () => {
    const broken = createFakeBackend();
    broken.loadAll.mockRejectedValue(new Error("no indexeddb"));
    registerScrollbackBackend(broken);

    await hydrateTerminalScrollback();

    expect(isScrollbackReady()).toBe(true);
    expect(logError).toHaveBeenCalled();
  });

  it("flushes pending writes when the window is hidden", async () => {
    await hydrateTerminalScrollback();
    setScrollback("key", "value");
    expect(backend.save).not.toHaveBeenCalled();

    window.dispatchEvent(new Event("pagehide"));
    await vi.advanceTimersByTimeAsync(0);

    expect(backend.save).toHaveBeenCalledWith("key", "value");
  });

  it("logs and continues when the legacy store is malformed", async () => {
    localStorage.setItem("terminal-store", "{not json");

    await hydrateTerminalScrollback();

    expect(logError).toHaveBeenCalled();
    expect(localStorage.getItem("terminal-store")).toBeNull();
  });
});
