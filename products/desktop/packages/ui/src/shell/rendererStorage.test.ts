import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { clearCapturedLogs, formatCapturedLogs } from "./logCapture";
import { createPersistOptions, WRITE_DEBOUNCE_MS } from "./rendererStorage";

type RendererStorageModule = typeof import("./rendererStorage");

async function importFreshRendererStorage(): Promise<RendererStorageModule> {
  vi.resetModules();
  return await import("./rendererStorage");
}

/** Fresh module with fake timers and a backend already registered. */
async function setupRegisteredBackend(data: Record<string, string> = {}) {
  vi.useFakeTimers();
  const module = await importFreshRendererStorage();
  const backend = fakeBackend(data);
  module.registerRendererStateStorage(backend);
  return { module, storage: jsonStorageOf(module), backend };
}

function fakeBackend(data: Record<string, string>) {
  return {
    getItem: vi.fn(async (key: string) => data[key] ?? null),
    setItem: vi.fn(async (key: string, value: string) => {
      data[key] = value;
    }),
    removeItem: vi.fn(async (key: string) => {
      delete data[key];
    }),
  };
}

function jsonStorageOf(module: RendererStorageModule) {
  const storage = module.electronStorage;
  if (!storage) {
    throw new Error("electronStorage is not defined");
  }
  return storage;
}

describe("rendererStorage", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("serves reads issued before the host registers its storage", async () => {
    const module = await importFreshRendererStorage();
    const storage = jsonStorageOf(module);

    const read = storage.getItem("settings-storage");

    module.registerRendererStateStorage(
      fakeBackend({
        "settings-storage": JSON.stringify({
          state: { defaultInitialTaskMode: "last_used" },
          version: 0,
        }),
      }),
    );

    await expect(read).resolves.toMatchObject({
      state: { defaultInitialTaskMode: "last_used" },
    });
  });

  it("drops writes racing the initial read, then writes through", async () => {
    vi.useFakeTimers();
    const module = await importFreshRendererStorage();
    const storage = jsonStorageOf(module);
    const backend = fakeBackend({
      "settings-storage": JSON.stringify({ state: { mode: "saved" } }),
    });

    const read = storage.getItem("settings-storage");
    const racingWrite = storage.setItem("settings-storage", {
      state: { mode: "default" },
      version: 0,
    });

    module.registerRendererStateStorage(backend);
    await Promise.all([read, racingWrite]);
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    expect(backend.setItem).not.toHaveBeenCalled();

    await storage.setItem("settings-storage", {
      state: { mode: "changed" },
      version: 0,
    });
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    expect(backend.setItem).toHaveBeenCalledTimes(1);
  });

  it("passes writes through for keys that were never read", async () => {
    vi.useFakeTimers();
    const module = await importFreshRendererStorage();
    const storage = jsonStorageOf(module);
    const backend = fakeBackend({});

    await storage.setItem("write-only", {
      state: { value: 1 },
      version: 0,
    });
    module.registerRendererStateStorage(backend);
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);

    expect(backend.setItem).toHaveBeenCalledTimes(1);
  });

  it("settles concurrent initial reads of the same key once", async () => {
    vi.useFakeTimers();
    const module = await importFreshRendererStorage();
    const storage = jsonStorageOf(module);
    const backend = fakeBackend({
      "settings-storage": JSON.stringify({
        state: { mode: "saved" },
        version: 0,
      }),
    });

    const first = storage.getItem("settings-storage");
    const second = storage.getItem("settings-storage");
    module.registerRendererStateStorage(backend);

    await expect(first).resolves.toMatchObject({ state: { mode: "saved" } });
    await expect(second).resolves.toMatchObject({ state: { mode: "saved" } });

    await storage.setItem("settings-storage", {
      state: { mode: "changed" },
      version: 0,
    });
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    expect(backend.setItem).toHaveBeenCalledTimes(1);
  });

  it("marks a key settled when the initial read rejects so later writes pass", async () => {
    vi.useFakeTimers();
    const module = await importFreshRendererStorage();
    const storage = jsonStorageOf(module);
    const backend = fakeBackend({});
    backend.getItem.mockRejectedValueOnce(new Error("backend unavailable"));

    const read = storage.getItem("settings-storage");
    module.registerRendererStateStorage(backend);
    await expect(read).rejects.toThrow("backend unavailable");

    await storage.setItem("settings-storage", {
      state: { mode: "changed" },
      version: 0,
    });
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    expect(backend.setItem).toHaveBeenCalledTimes(1);
  });

  it("forwards removeItem issued before and after registration", async () => {
    const module = await importFreshRendererStorage();
    const storage = jsonStorageOf(module);
    const backend = fakeBackend({});

    const removal = storage.removeItem("settings-storage");
    module.registerRendererStateStorage(backend);
    await removal;
    expect(backend.removeItem).toHaveBeenCalledTimes(1);

    await storage.removeItem("settings-storage");
    expect(backend.removeItem).toHaveBeenCalledTimes(2);
  });

  it("keeps in-flight waiters on the first backend and routes later calls to the second", async () => {
    const module = await importFreshRendererStorage();
    const storage = jsonStorageOf(module);
    const first = fakeBackend({
      "settings-storage": JSON.stringify({
        state: { from: "first" },
        version: 0,
      }),
    });
    const second = fakeBackend({
      "settings-storage": JSON.stringify({
        state: { from: "second" },
        version: 0,
      }),
    });

    const read = storage.getItem("settings-storage");
    module.registerRendererStateStorage(first);
    module.registerRendererStateStorage(second);

    await expect(read).resolves.toMatchObject({ state: { from: "first" } });

    await expect(storage.getItem("settings-storage")).resolves.toMatchObject({
      state: { from: "second" },
    });
    expect(second.getItem).toHaveBeenCalledTimes(1);
  });

  it("hydrates a store created before the host storage registers", async () => {
    const module = await importFreshRendererStorage();
    const backend = fakeBackend({
      "settings-storage": JSON.stringify({
        state: { defaultInitialTaskMode: "last_used" },
        version: 0,
      }),
    });

    const useStore = create<{ defaultInitialTaskMode: string }>()(
      persist(() => ({ defaultInitialTaskMode: "plan" }), {
        name: "settings-storage",
        storage: jsonStorageOf(module),
      }),
    );

    expect(useStore.getState().defaultInitialTaskMode).toBe("plan");

    module.registerRendererStateStorage(backend);
    await vi.waitFor(() => {
      expect(useStore.getState().defaultInitialTaskMode).toBe("last_used");
    });

    useStore.setState({ defaultInitialTaskMode: "plan" });
    await vi.waitFor(async () => {
      await module.flushRendererStateWrites();
      expect(backend.setItem).toHaveBeenCalled();
    });
    const persisted = JSON.parse(
      backend.setItem.mock.calls[backend.setItem.mock.calls.length - 1][1],
    );
    expect(persisted.state.defaultInitialTaskMode).toBe("plan");
  });

  it("coalesces a burst of writes into one backend write with the latest value", async () => {
    const { storage, backend } = await setupRegisteredBackend();

    await storage.setItem("drafts", { state: { value: 1 }, version: 0 });
    await storage.setItem("drafts", { state: { value: 2 }, version: 0 });
    await storage.setItem("drafts", { state: { value: 3 }, version: 0 });

    expect(backend.setItem).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    expect(backend.setItem).toHaveBeenCalledTimes(1);
    const persisted = JSON.parse(backend.setItem.mock.calls[0][1]);
    expect(persisted.state.value).toBe(3);
  });

  it("flushes at the max-wait bound during sustained writes", async () => {
    const { storage, backend } = await setupRegisteredBackend();

    // Write every 500ms for 6s: a plain trailing debounce would never fire,
    // the max-wait bound forces a flush mid-burst.
    for (let i = 0; i < 12; i++) {
      await storage.setItem("drafts", { state: { value: i }, version: 0 });
      await vi.advanceTimersByTimeAsync(500);
    }
    expect(backend.setItem.mock.calls.length).toBeGreaterThanOrEqual(1);

    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    const last = backend.setItem.mock.calls.at(-1);
    expect(JSON.parse(last?.[1] ?? "{}").state.value).toBe(11);
  });

  it("lands the pending coalesced write before serving a read", async () => {
    const { storage, backend } = await setupRegisteredBackend({
      drafts: JSON.stringify({ state: { value: "stale" }, version: 0 }),
    });

    await storage.setItem("drafts", { state: { value: "fresh" }, version: 0 });

    await expect(storage.getItem("drafts")).resolves.toMatchObject({
      state: { value: "fresh" },
    });
    expect(backend.setItem).toHaveBeenCalledTimes(1);

    // The read consumed the pending write; the debounce timer must not fire
    // a duplicate.
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    expect(backend.setItem).toHaveBeenCalledTimes(1);
  });

  it("cancels a pending write when the key is removed", async () => {
    const { storage, backend } = await setupRegisteredBackend();

    await storage.setItem("drafts", { state: { value: 1 }, version: 0 });
    await storage.removeItem("drafts");
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);

    expect(backend.setItem).not.toHaveBeenCalled();
    expect(backend.removeItem).toHaveBeenCalledTimes(1);
  });

  it("flushRendererStateWrites persists pending state immediately", async () => {
    const { module, storage, backend } = await setupRegisteredBackend();

    await storage.setItem("drafts", { state: { value: 1 }, version: 0 });
    await module.flushRendererStateWrites();
    expect(backend.setItem).toHaveBeenCalledTimes(1);

    // The debounce timer was cancelled by the flush; no duplicate write.
    await vi.advanceTimersByTimeAsync(WRITE_DEBOUNCE_MS);
    expect(backend.setItem).toHaveBeenCalledTimes(1);
  });

  describe("createPersistOptions", () => {
    beforeEach(() => {
      clearCapturedLogs();
    });

    // Every branch that can't produce usable state must resolve to the reset
    // slice rather than letting zustand drop the payload with a bare
    // console.error — the exact failure this helper exists to prevent.
    it.each([
      ["no migrate is provided", undefined],
      [
        "the store migrate throws",
        () => {
          throw new Error("boom");
        },
      ],
      ["the store migrate returns undefined", () => undefined],
      ["the store migrate returns null", () => null],
      ["the store migrate rejects", () => Promise.reject(new Error("boom"))],
      ["the store migrate resolves nothing", () => Promise.resolve(undefined)],
    ])("resets when %s", async (_case, migrate) => {
      const options = createPersistOptions<{ value: number }>({
        name: "reset-case",
        version: 2,
        resetState: () => ({ value: 0 }),
        // biome-ignore lint/suspicious/noExplicitAny: exercising failure inputs
        migrate: migrate as any,
      });

      // `await` resolves both the sync and async (rejected-promise) paths.
      expect(await options.migrate?.({ value: 99 }, 1)).toEqual({ value: 0 });
    });

    it("defaults the reset slice to an empty object when resetState is omitted", async () => {
      const options = createPersistOptions<{ value: number }>({
        name: "empty-reset",
        version: 1,
      });

      expect(await options.migrate?.({ value: 99 }, 0)).toEqual({});
    });

    it("uses the store migrate's result when it succeeds", async () => {
      const options = createPersistOptions<{ value: number }>({
        name: "happy-migrate",
        version: 2,
        resetState: () => ({ value: 0 }),
        migrate: (persisted) => ({
          value: (persisted as { value: number }).value + 1,
        }),
      });

      expect(await options.migrate?.({ value: 41 }, 1)).toEqual({ value: 42 });
      // A successful migration is not a reset, so nothing is logged.
      expect(formatCapturedLogs()).not.toContain(
        "Resetting persisted store to defaults",
      );
    });

    it("logs the reset through the shell logger, not console.error", async () => {
      const options = createPersistOptions<{ value: number }>({
        name: "logged-reset",
        version: 2,
        resetState: () => ({ value: 0 }),
        migrate: () => {
          throw new Error("boom");
        },
      });

      await options.migrate?.({ value: 99 }, 1);

      const logs = formatCapturedLogs();
      expect(logs).toContain("renderer-storage");
      expect(logs).toContain("Resetting persisted store to defaults");
    });
  });
});
