import {
  pendingTaskPromptStoreApi,
  usePendingTaskPromptStore,
} from "@posthog/ui/shell/pendingTaskPromptStore";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function resetStore(): void {
  usePendingTaskPromptStore.setState({ byKey: {}, _hasHydrated: false });
}

describe("pendingTaskPromptStore", () => {
  beforeEach(() => {
    resetStore();
    let now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => {
      now += 1_000;
      return now;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetStore();
  });

  it("stamps createdAt when a prompt is set", () => {
    pendingTaskPromptStoreApi.set("k1", { promptText: "hi", attachments: [] });
    const stored = pendingTaskPromptStoreApi.get("k1");
    expect(stored?.promptText).toBe("hi");
    expect(typeof stored?.createdAt).toBe("number");
  });

  it("moves an entry to a new key, preserving its contents", () => {
    pendingTaskPromptStoreApi.set("pending-1", {
      promptText: "draft",
      attachments: [],
    });
    const before = pendingTaskPromptStoreApi.get("pending-1");

    pendingTaskPromptStoreApi.move("pending-1", "task-42");

    expect(pendingTaskPromptStoreApi.get("pending-1")).toBeUndefined();
    expect(pendingTaskPromptStoreApi.get("task-42")).toEqual(before);
  });

  it("clears an entry by key", () => {
    pendingTaskPromptStoreApi.set("k1", { promptText: "x", attachments: [] });
    pendingTaskPromptStoreApi.clear("k1");
    expect(pendingTaskPromptStoreApi.get("k1")).toBeUndefined();
  });

  it("returns every surviving entry newest-first for recovery", () => {
    pendingTaskPromptStoreApi.set("old", {
      promptText: "old",
      attachments: [],
    });
    pendingTaskPromptStoreApi.set("mid", {
      promptText: "mid",
      attachments: [],
    });
    pendingTaskPromptStoreApi.set("new", {
      promptText: "new",
      attachments: [],
    });

    const recovered = pendingTaskPromptStoreApi.getAllNewestFirst();

    expect(recovered.map((r) => r.key)).toEqual(["new", "mid", "old"]);
  });

  it("caps stored prompts to the newest, dropping the oldest", () => {
    for (let i = 0; i < 22; i++) {
      pendingTaskPromptStoreApi.set(`k${i}`, {
        promptText: `p${i}`,
        attachments: [],
      });
    }

    const recovered = pendingTaskPromptStoreApi.getAllNewestFirst();

    expect(recovered).toHaveLength(20);
    expect(pendingTaskPromptStoreApi.get("k0")).toBeUndefined();
    expect(pendingTaskPromptStoreApi.get("k1")).toBeUndefined();
    expect(pendingTaskPromptStoreApi.get("k21")).toBeDefined();
  });

  it("whenHydrated resolves immediately once the store has hydrated", async () => {
    usePendingTaskPromptStore.getState().setHasHydrated(true);
    await expect(
      pendingTaskPromptStoreApi.whenHydrated(),
    ).resolves.toBeUndefined();
  });

  it("whenHydrated waits for hydration to complete", async () => {
    let resolved = false;
    const waiter = pendingTaskPromptStoreApi.whenHydrated().then(() => {
      resolved = true;
    });

    expect(resolved).toBe(false);
    usePendingTaskPromptStore.getState().setHasHydrated(true);
    await waiter;
    expect(resolved).toBe(true);
  });
});
