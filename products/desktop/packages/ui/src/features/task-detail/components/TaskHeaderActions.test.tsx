import type { Task } from "@posthog/shared/domain-types";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { useWorkspace, useWorkspaceLoaded } = vi.hoisted(() => ({
  useWorkspace: vi.fn(),
  useWorkspaceLoaded: vi.fn(),
}));

vi.mock(
  "@posthog/ui/features/workspace/useWorkspace",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("@posthog/ui/features/workspace/useWorkspace")
      >();
    return {
      useWorkspace,
      useWorkspaceLoaded,
      useIsCloudTask: (task: Task) =>
        actual.isCloudTask(task, useWorkspace(task.id)),
    };
  },
);
vi.mock("@posthog/ui/features/code-review/hooks/useDiffStatsToggle", () => ({
  useDiffStatsToggle: () => ({
    filesChanged: 0,
    linesAdded: 0,
    linesRemoved: 0,
    isOpen: false,
    toggle: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/autoresearch/AutoresearchHeaderButton", () => ({
  AutoresearchHeaderButton: () => null,
}));
vi.mock(
  "@posthog/ui/features/git-interaction/components/BranchSelector",
  () => ({
    BranchSelector: () => null,
  }),
);
vi.mock(
  "@posthog/ui/features/git-interaction/components/TaskActionsMenu",
  () => ({
    // Renders the cloud verdict, which is what this row derives.
    TaskActionsMenu: ({ isCloud }: { isCloud: boolean }) => (
      <div data-testid="task-menu">{isCloud ? "cloud" : "local"}</div>
    ),
  }),
);
// Reads the session store and the pi session controller from the container,
// which these renders don't wire up.
vi.mock("./TaskOverflowMenu", () => ({
  TaskOverflowMenu: () => <div>task actions</div>,
}));
vi.mock("@posthog/ui/features/diff-stats/DiffStatsBadge", () => ({
  DiffStatsBadge: () => null,
}));
// Needs an authenticated client, so a TRPC provider these renders don't set up.
vi.mock("./TaskAnalysisButton", () => ({
  TaskAnalysisButton: () => null,
}));
// Reads the route, which these renders don't provide. The Code scene's answer
// is false, and that is the row this test covers.
vi.mock("@posthog/ui/features/navigation/useReviewInRightPanel", () => ({
  useReviewInRightPanel: () => false,
}));
vi.mock("@posthog/ui/primitives/Tooltip", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => children,
}));

import { TaskHeaderActions } from "./TaskHeaderActions";

function renderActions(
  task: Task = { id: "task-1", title: "Fix the bug" } as Task,
) {
  render(<TaskHeaderActions task={task} />);
}

describe("TaskHeaderActions", () => {
  it("does not show workspace-dependent actions before workspaces load", () => {
    useWorkspace.mockReturnValue(null);
    useWorkspaceLoaded.mockReturnValue(false);

    renderActions();

    expect(screen.queryByTestId("task-menu")).not.toBeInTheDocument();
    // The overflow menu needs no workspace, so it is the one part that stays.
    expect(screen.getByText("task actions")).toBeInTheDocument();
  });

  it.each([
    ["a cloud workspace", { mode: "cloud" }, undefined],
    ["a cloud run with no local workspace row", null, "cloud"],
  ])("reads %s as a cloud task", (_case, workspace, runEnvironment) => {
    useWorkspace.mockReturnValue(workspace);
    useWorkspaceLoaded.mockReturnValue(true);

    renderActions({
      id: "task-1",
      title: "Fix the bug",
      ...(runEnvironment
        ? { latest_run: { environment: runEnvironment } }
        : {}),
    } as Task);

    expect(screen.getByTestId("task-menu")).toHaveTextContent("cloud");
  });
});
