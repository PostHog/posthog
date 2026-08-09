import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
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
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@posthog/ui/router/useAppView", () => ({ useAppView }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
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
  navigateToInbox,
  navigateToLoops: vi.fn(),
  navigateToMcpServers,
  navigateToSkills,
  navigateToWebsiteCommandCenter: vi.fn(),
  navigateToWebsiteMcpServers: vi.fn(),
  navigateToWebsiteSkills: vi.fn(),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput: vi.fn() }));
vi.mock("@posthog/ui/shell/commandMenuStore", () => ({
  useCommandMenuStore: (selector: (s: { open: () => void }) => unknown) =>
    selector({ open: openCommandMenu }),
}));
vi.mock("@posthog/ui/features/command-center/commandCenterStore", () => ({
  useCommandCenterStore: (
    selector: (s: { cells: (string | null)[] }) => unknown,
  ) => selector({ cells: [] }),
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({ counts: { pulls: 0 } }),
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
    ["inbox", "Inbox"],
    ["command-center", "Command Center"],
    ["activity", "Activity"],
    ["configure", "Configure"],
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

    expect(position("Inbox")).toBeLessThan(position("Activity"));
    expect(position("Activity")).toBeLessThan(position("Loops"));
    expect(position("Inbox")).toBeLessThan(position("Loops"));
  });

  it("tracks top-level clicks with in_more false", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: /Inbox/ }));

    expect(navigateToInbox).toHaveBeenCalledTimes(1);
    // `layout` separates these from ChannelNav's identically-named clicks.
    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED,
      { item: "inbox", in_more: false, layout: "code" },
    );
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
