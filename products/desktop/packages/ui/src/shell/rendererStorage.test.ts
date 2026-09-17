import { afterEach, describe, expect, it, vi } from "vitest";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { WRITE_DEBOUNCE_MS } from "./rendererStorage";

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
});
