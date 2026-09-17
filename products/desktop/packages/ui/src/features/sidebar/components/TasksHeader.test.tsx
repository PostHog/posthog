import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { featureFlagEnabled, track } = vi.hoisted(() => ({
  featureFlagEnabled: { value: true },
  track: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => featureFlagEnabled.value,
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({ os: { selectDirectory: { query: vi.fn() } } }),
}));
vi.mock("@posthog/ui/features/auth/useMeQuery", () => ({
  useMeQuery: () => ({ data: { is_staff: false } }),
}));
vi.mock("@posthog/ui/features/folders/useFolders", () => ({
  useFolders: () => ({ addFolder: vi.fn() }),
}));
vi.mock("@posthog/ui/features/sidebar/useHoldSidebarPeek", () => ({
  useHoldSidebarPeek: () => vi.fn(),
}));
vi.mock("@posthog/ui/shell/commandMenuStore", () => ({
  useCommandMenuStore: (selector: (state: { open: () => void }) => unknown) =>
    selector({ open: vi.fn() }),
}));

import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { TasksHeader } from "./TasksHeader";

describe("TasksHeader", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    featureFlagEnabled.value = true;
    useSidebarStore.setState({
      channelsEnabled: false,
      organizeMode: "by-project",
      sortMode: "updated",
    });
  });

  it("switches modes from the panel title and changes the available actions", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <TasksHeader />
      </Theme>,
    );

    const listOption = screen.getByRole("button", { name: "List" });
    const channelsOption = screen.getByRole("button", { name: "Channels" });
    expect(listOption).toHaveAttribute("aria-pressed", "true");
    expect(listOption).toHaveAttribute("data-active", "true");
    expect(listOption).toHaveClass("data-[active]:bg-accent-4");
    expect(listOption).toHaveClass("data-[active]:font-medium");
    expect(listOption).toHaveClass("text-xs");
    expect(channelsOption).toHaveClass("text-xs");
    expect(channelsOption).not.toHaveAttribute("data-active");
    expect(
      screen.getByRole("button", { name: "Filter tasks" }),
    ).toBeInTheDocument();

    await user.click(channelsOption);

    expect(channelsOption).toHaveAttribute("aria-pressed", "true");
    expect(channelsOption).toHaveAttribute("data-active", "true");
    expect(listOption).not.toHaveAttribute("data-active");
    expect(
      screen.queryByRole("button", { name: "Filter tasks" }),
    ).not.toBeInTheDocument();
    expect(track).toHaveBeenCalledWith(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "toggle_channels",
      surface: "nav",
    });
  });

  it("groups the task list by repository or date", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <TasksHeader />
      </Theme>,
    );

    await user.click(screen.getByLabelText("Filter tasks"));

    expect(await screen.findByText("Group by")).toBeInTheDocument();
    expect(screen.getByText("Repository")).toHaveAttribute(
      "aria-checked",
      "true",
    );

    await user.click(screen.getByText("Date"));

    expect(useSidebarStore.getState().organizeMode).toBe("chronological");
    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.TASK_LIST_GROUPING_CHANGED,
      { group_by: "date", sort_by: "updated", surface: "sidebar" },
    );
  });

  it("hides the mode selector when Channels is unavailable", () => {
    featureFlagEnabled.value = false;

    render(
      <Theme>
        <TasksHeader />
      </Theme>,
    );

    expect(screen.getByText("List")).toBeInTheDocument();
    expect(screen.queryByText("Channels")).not.toBeInTheDocument();
  });
});
