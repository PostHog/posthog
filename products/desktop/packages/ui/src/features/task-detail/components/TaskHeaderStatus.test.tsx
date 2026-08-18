import type { Task } from "@posthog/shared/domain-types";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The status comes from live session/workspace state and a per-task tRPC query,
// none of which a unit test has. Stubbed at the module boundary, as
// ChannelItemRow.test.tsx does for the same reason.
const mocks = vi.hoisted(() => ({
  bluebird: true,
  status: null as TaskStatusInput | null,
  togglePin: vi.fn(async (_taskId: string) => undefined),
  openExternalUrl: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@posthog/ui/features/feature-flags/useBluebirdFlag", () => ({
  useBluebirdFlag: () => mocks.bluebird,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useTaskStatusInput: () => mocks.status,
}));
vi.mock("@posthog/ui/features/sidebar/usePinnedTasks", () => ({
  usePinnedTasks: () => ({ togglePin: mocks.togglePin }),
}));
vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: mocks.openExternalUrl,
}));
vi.mock("@posthog/ui/primitives/toast", () => ({ toast: mocks.toast }));

import { TaskHeaderActions, TaskHeaderMark } from "./TaskHeaderStatus";

const task = { id: "task-1" } as Task;

function renderMark() {
  return render(
    <Theme>
      <TaskHeaderMark task={task} mode="cloud" />
    </Theme>,
  );
}

function renderActions() {
  return render(
    <Theme>
      <TaskHeaderActions task={task} />
    </Theme>,
  );
}

describe("TaskHeaderStatus", () => {
  beforeEach(() => {
    mocks.bluebird = true;
    mocks.status = { workspaceMode: "cloud" };
    mocks.togglePin.mockClear();
    mocks.togglePin.mockResolvedValue(undefined);
    mocks.openExternalUrl.mockClear();
    mocks.toast.success.mockClear();
    mocks.toast.error.mockClear();
  });

  it.each([
    ["needs your input", { needsPermission: true }, "Needs your input"],
    ["a settled session", {}, "All caught up"],
  ])(
    "names the state under project-bluebird for %s",
    (_case, status: TaskStatusInput, label) => {
      mocks.status = { workspaceMode: "cloud", ...status };
      renderMark();

      expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
    },
  );

  it("keeps the workspace-mode glyph when project-bluebird is off", () => {
    mocks.bluebird = false;
    const { container } = renderMark();

    // The mode glyph carries its name in a tooltip rather than a role, so the
    // dot's absence is what says the old header is still drawn.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("moves where the session runs into a badge, so cloud stays silent", () => {
    mocks.status = { workspaceMode: "local" };
    const { rerender } = renderActions();

    // A fact about the session, not a control: it names itself and stops there,
    // so the pin is the only thing in the row you can press.
    expect(screen.getByRole("img", { name: "Local" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);

    mocks.status = { workspaceMode: "cloud" };
    rerender(
      <Theme>
        <TaskHeaderActions task={task} />
      </Theme>,
    );

    expect(
      screen.queryByRole("img", { name: "Local" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["pinned", true, "Unpin", "Unpinned"],
    ["unpinned", false, "Pin", "Pinned"],
  ])(
    "toggles the pin from the header when %s, and says so",
    async (_case, isPinned: boolean, label: string, confirmation: string) => {
      mocks.status = { workspaceMode: "cloud", isPinned };
      renderActions();

      await userEvent.click(screen.getByRole("button", { name: label }));

      expect(mocks.togglePin).toHaveBeenCalledWith("task-1");
      expect(mocks.toast.success).toHaveBeenCalledWith(confirmation);
    },
  );

  it("leaves the PR to the git control at the end of the row", () => {
    mocks.status = {
      workspaceMode: "cloud",
      prUrl: "https://github.com/PostHog/posthog/pull/1",
      prState: "open",
    };
    renderActions();

    expect(
      screen.queryByRole("button", { name: "PR ready for review" }),
    ).not.toBeInTheDocument();
  });

  it("reports a pin that didn't take, rather than leaving the mark to lie", async () => {
    mocks.status = { workspaceMode: "cloud", isPinned: false };
    mocks.togglePin.mockRejectedValueOnce(new Error("offline"));
    renderActions();

    await userEvent.click(screen.getByRole("button", { name: "Pin" }));

    expect(mocks.toast.error).toHaveBeenCalledWith(
      "Couldn't pin",
      expect.objectContaining({ description: "offline" }),
    );
  });

  it("opens the thread a session was filed from", async () => {
    mocks.status = {
      workspaceMode: "cloud",
      originProduct: "slack",
      slackThreadUrl: "https://example.slack.com/archives/C1/p1",
    };
    renderActions();

    await userEvent.click(
      screen.getByRole("button", { name: "Source: Slack" }),
    );

    expect(mocks.openExternalUrl).toHaveBeenCalledWith(
      "https://example.slack.com/archives/C1/p1",
    );
  });
});
