import type { TabsSnapshot } from "@posthog/shared";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { openFirstRunOnboardingTab } from "./firstRunOnboardingTab";

const emptySnapshot: TabsSnapshot = { windows: [], tabs: [] };

describe("openFirstRunOnboardingTab", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("opens one inactive onboarding tab for an identity", async () => {
    const storage = new Map<string, string>();
    vi.spyOn(stateStorage, "getItem").mockImplementation(
      async (key) => storage.get(key) ?? null,
    );
    vi.spyOn(stateStorage, "setItem").mockImplementation(async (key, value) => {
      storage.set(key, value);
    });
    const client = {
      getPrimaryWindowId: vi.fn().mockResolvedValue("window-1"),
      openTab: vi.fn().mockResolvedValue(emptySnapshot),
    };

    await Promise.all([
      openFirstRunOnboardingTab("us:2", client),
      openFirstRunOnboardingTab("us:2", client),
    ]);
    await openFirstRunOnboardingTab("us:2", client);

    expect(client.openTab).toHaveBeenCalledOnce();
    expect(client.openTab).toHaveBeenCalledWith(
      expect.objectContaining({
        windowId: "window-1",
        href: "/onboarding-landing",
        appView: "onboarding",
        activate: false,
      }),
    );
  });
});
