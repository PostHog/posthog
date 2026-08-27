import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  navigateBrowserTab: vi.fn(),
  openTaskInput: vi.fn(),
}));

vi.mock("@posthog/ui/features/browser-tabs/imperativeTabNavigation", () => ({
  navigateBrowserTab: mocks.navigateBrowserTab,
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTaskInput: mocks.openTaskInput,
}));

import { restoreTaskInputTab } from "./taskInputTab";

describe("restoreTaskInputTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("restores a failed space task to its original space", () => {
    restoreTaskInputTab("tab-1", "space-1");

    expect(mocks.navigateBrowserTab).toHaveBeenCalledWith(
      "tab-1",
      {
        href: "/spaces/space-1/new",
        title: "New task",
        channelId: "space-1",
      },
      expect.any(Function),
    );

    const navigateActiveTab = mocks.navigateBrowserTab.mock.calls[0]?.[2];
    navigateActiveTab();
    expect(mocks.openTaskInput).toHaveBeenCalledWith({ channelId: "space-1" });
  });

  it("restores an unscoped task to the Code composer", () => {
    restoreTaskInputTab("tab-1");

    const [, destination, navigateActiveTab] =
      mocks.navigateBrowserTab.mock.calls[0];
    expect(destination).toEqual({
      href: "/new",
      title: "New task",
      channelId: undefined,
    });
    navigateActiveTab();
    expect(mocks.openTaskInput).toHaveBeenCalledWith({ unscoped: true });
  });
});
