import type { TabsSnapshot } from "@posthog/shared";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ensureOnboardingTab,
  markOnboardingTabClosed,
  ONBOARDING_TAB_HREF,
  restoreOnboardingTab,
} from "./onboardingTab";

const storageKey = "first-run-onboarding-tab:us:2";
const emptySnapshot: TabsSnapshot = {
  windows: [
    {
      id: "window-1",
      isPrimary: true,
      bounds: null,
      activeTabId: "tab-1",
    },
  ],
  tabs: [],
};
const onboardingTab: TabsSnapshot["tabs"][number] = {
  id: "onboarding-tab",
  windowId: "window-1",
  href: ONBOARDING_TAB_HREF,
  viewState: { title: "Onboarding" },
  dashboardId: null,
  taskId: null,
  channelId: null,
  channelSection: null,
  appView: "onboarding",
  position: 2_000,
  scrollState: null,
  createdAt: 1,
  lastActiveAt: 1,
};
const onboardingSnapshot: TabsSnapshot = {
  ...emptySnapshot,
  tabs: [onboardingTab],
};

function mockStorage(initial?: string): Map<string, string> {
  const storage = new Map<string, string>();
  if (initial) storage.set(storageKey, initial);
  vi.spyOn(stateStorage, "getItem").mockImplementation(
    async (key) => storage.get(key) ?? null,
  );
  vi.spyOn(stateStorage, "setItem").mockImplementation(async (key, value) => {
    storage.set(key, value);
  });
  vi.spyOn(stateStorage, "removeItem").mockImplementation(async (key) => {
    storage.delete(key);
  });
  return storage;
}

function mockClient(snapshot: TabsSnapshot) {
  return {
    getSnapshot: vi.fn().mockResolvedValue(snapshot),
    getPrimaryWindowId: vi.fn().mockResolvedValue("window-1"),
    openTab: vi.fn().mockResolvedValue(snapshot),
  };
}

describe("onboarding tab", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("opens one inactive tab when the user has not closed it", async () => {
    mockStorage();
    const client = mockClient(emptySnapshot);

    await Promise.all([
      ensureOnboardingTab("us:2", client),
      ensureOnboardingTab("us:2", client),
    ]);

    expect(client.openTab).toHaveBeenCalledOnce();
    expect(client.openTab).toHaveBeenCalledWith(
      expect.objectContaining({
        windowId: "window-1",
        href: ONBOARDING_TAB_HREF,
        appView: "onboarding",
        activate: false,
      }),
    );
    expect(stateStorage.setItem).not.toHaveBeenCalled();
  });

  it("does not open a duplicate tab", async () => {
    mockStorage();
    const client = mockClient(onboardingSnapshot);

    await ensureOnboardingTab("us:2", client);

    expect(client.openTab).not.toHaveBeenCalled();
  });

  it("does not restore a tab after the user closes it", async () => {
    mockStorage("dismissed");
    const client = mockClient(emptySnapshot);

    await ensureOnboardingTab("us:2", client);

    expect(client.openTab).not.toHaveBeenCalled();
  });

  it("migrates the old opened marker to the close state", async () => {
    const storage = mockStorage("opened");
    const client = mockClient(emptySnapshot);

    await ensureOnboardingTab("us:2", client);

    expect(storage.get(storageKey)).toBe("dismissed");
    expect(client.openTab).not.toHaveBeenCalled();
  });

  it("removes the old marker when the tab is still open", async () => {
    const storage = mockStorage("opened");
    const client = mockClient(onboardingSnapshot);

    await ensureOnboardingTab("us:2", client);

    expect(storage.has(storageKey)).toBe(false);
    expect(client.openTab).not.toHaveBeenCalled();
  });

  it("records an onboarding close and lets settings restore it", async () => {
    const storage = mockStorage();

    await markOnboardingTabClosed("us:2", [onboardingTab]);
    expect(storage.get(storageKey)).toBe("dismissed");

    await restoreOnboardingTab("us:2");
    expect(storage.has(storageKey)).toBe(false);
  });

  it("ignores closes for other tabs", async () => {
    mockStorage();

    await markOnboardingTabClosed("us:2", [
      { href: "/activity", appView: "activity" },
    ]);

    expect(stateStorage.setItem).not.toHaveBeenCalled();
  });
});
