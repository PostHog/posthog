import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const {
  track,
  useAppView,
  navigateToInbox,
  navigateToAgents,
  navigateToSkills,
  navigateToMcpServers,
  navigateToCommandCenter,
  navigateToActivity,
  openCommandMenu,
  openSettings,
  openBrowserTab,
} = vi.hoisted(() => ({
  track: vi.fn(),
  useAppView: vi.fn(),
  navigateToInbox: vi.fn(),
  navigateToAgents: vi.fn(),
  navigateToSkills: vi.fn(),
  navigateToMcpServers: vi.fn(),
  navigateToCommandCenter: vi.fn(),
  navigateToActivity: vi.fn(),
  openCommandMenu: vi.fn(),
  openSettings: vi.fn(),
  openBrowserTab: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@posthog/ui/router/useAppView", () => ({ useAppView }));
// Channel reports defaults off here so the Inbox item renders; the flag-on
// test flips it via `channelReportsFlag`.
let channelReportsFlag = false;
let reportsInboxFlag = false;
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: (flag: string) =>
    flag === "posthog-desktop-channel-reports"
      ? channelReportsFlag
      : flag === "posthog-desktop-reports-inbox"
        ? reportsInboxFlag
        : true,
}));
vi.mock("@posthog/ui/features/feature-flags/useChannelReportsEnabled", () => ({
  useChannelReportsEnabled: () => channelReportsFlag,
}));
vi.mock("@posthog/ui/features/feature-flags/useReportsInboxEnabled", () => ({
  useReportsInboxEnabled: () => reportsInboxFlag,
}));
// These tests pin the legacy layout (flag off), where the "Enable channels"
// toggle row is present.
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => false,
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToActivity,
  navigateToAgents,
  navigateToCommandCenter,
  navigateToContext: vi.fn(),
  navigateToInbox,
  navigateToLoops: vi.fn(),
  navigateToMcpServers,
  navigateToSkills,
  navigateToWebsiteCommandCenter: vi.fn(),
  navigateToWebsiteContext: vi.fn(),
  navigateToWebsiteMcpServers: vi.fn(),
  navigateToWebsiteSkills: vi.fn(),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput: vi.fn() }));
vi.mock("@posthog/ui/features/browser-tabs/useOpenBrowserTab", () => ({
  useOpenBrowserTab: () => openBrowserTab,
}));
vi.mock("@posthog/ui/features/settings/hooks/useOpenSettings", () => ({
  openSettings,
}));
vi.mock("@posthog/ui/shell/commandMenuStore", () => ({
  useCommandMenuStore: (selector: (s: { open: () => void }) => unknown) =>
    selector({ open: openCommandMenu }),
}));
vi.mock("@posthog/ui/features/command-center/commandCenterStore", () => ({
  useCommandCenterStore: (
    selector: (s: { cells: (string | null)[] }) => unknown,
  ) => selector({ cells: [] }),
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxDecisionCount", () => ({
  useInboxDecisionCount: () => 0,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({ scopedReports: [], counts: { pulls: 0 } }),
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({ data: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskActivity", () => ({
  useTaskActivity: () => ({ items: [], unreadCount: 0, isLoading: false }),
}));
vi.mock("@tanstack/react-router", () => ({
  useRouterState: () => false,
}));

import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { SidebarNavSection } from "./SidebarNavSection";

function renderNav() {
  return render(
    <Theme>
      <SidebarNavSection />
    </Theme>,
  );
}

describe("SidebarNavSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAppView.mockReturnValue({ type: "task-input" });
    useSidebarStore.setState({
      navItemOverrides: {},
      navItemOrder: [],
      channelsEnabled: true,
    });
  });

  it("renders Search directly and removes the More dropdown", () => {
    renderNav();

    expect(screen.getByRole("button", { name: /Search/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "More" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["inbox", "Self-driving"],
    ["command-center", "Command Center"],
    ["activity", "Activity"],
    ["configure", "Settings"],
    ["loops", "Loops"],
  ] as const)("removes %s from the sidebar when hidden", (id, label) => {
    useSidebarStore.setState({ navItemOverrides: { [id]: false } });
    renderNav();

    expect(screen.queryByText(label)).not.toBeInTheDocument();
  });

  it("renders Activity directly under Inbox by default", () => {
    renderNav();

    const labels = screen
      .getAllByRole("button")
      .map((button) => button.textContent ?? "");
    const position = (label: string) =>
      labels.findIndex((text) => text.includes(label));

    expect(position("Self-driving")).toBeLessThan(position("Activity"));
    expect(position("Activity")).toBeLessThan(position("Loops"));
    expect(position("Self-driving")).toBeLessThan(position("Loops"));
  });

  it("tracks top-level clicks with in_more false", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /Self-driving/ }));

    expect(navigateToInbox).toHaveBeenCalledTimes(1);
    // `layout` separates these from the nav rail's identically-named clicks.
    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED,
      { item: "inbox", in_more: false, layout: "code" },
    );
  });

  it("opens a destination in a new tab on Cmd-click", () => {
    renderNav();

    fireEvent.click(screen.getByRole("button", { name: /Self-driving/ }), {
      metaKey: true,
    });

    expect(openBrowserTab).toHaveBeenCalledWith("/inbox");
    expect(navigateToInbox).not.toHaveBeenCalled();
  });

  it("keeps Settings in the current window on Cmd-click", () => {
    renderNav();

    fireEvent.click(screen.getByRole("button", { name: /Settings/ }), {
      metaKey: true,
    });

    expect(openSettings).toHaveBeenCalledOnce();
    expect(openBrowserTab).not.toHaveBeenCalled();
  });

  it("removes the Inbox item when channel reports replace the inbox", () => {
    channelReportsFlag = true;
    try {
      renderNav();
      expect(
        screen.queryByRole("button", { name: /Self-driving/ }),
      ).not.toBeInTheDocument();
    } finally {
      channelReportsFlag = false;
    }
  });

  it("keeps the Inbox item when the reports inbox reclaims the slot", () => {
    channelReportsFlag = true;
    reportsInboxFlag = true;
    try {
      renderNav();
      expect(
        screen.getByRole("button", { name: /Self-driving/ }),
      ).toBeInTheDocument();
    } finally {
      channelReportsFlag = false;
      reportsInboxFlag = false;
    }
  });

  it("does not render the Channels mode toggle in navigation", () => {
    renderNav();

    expect(screen.queryByText("Channels")).not.toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("keeps Activity visible when Tasks mode is selected", () => {
    useSidebarStore.setState({ channelsEnabled: false });

    renderNav();

    expect(screen.getByText("Activity")).toBeInTheDocument();
  });
});
