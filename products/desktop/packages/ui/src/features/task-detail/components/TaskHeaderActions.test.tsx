import type { Task } from "@posthog/shared/domain-types";
import { Theme } from "@radix-ui/themes";
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
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (selector: (state: { status: string }) => unknown) =>
    selector({ status: "authenticated" }),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/sessions/useSession", () => ({
  useSessionForTask: () => null,
}));
vi.mock("@posthog/ui/features/sessions/hooks/useSessionCallbacks", () => ({
  useSessionCallbacks: () => ({ initiateHandoffToCloud: vi.fn() }),
}));
vi.mock("@posthog/ui/features/sessions/handoffDialogStore", () => ({
  useHandoffDialogStore: (selector: (state: object) => unknown) =>
    selector({
      confirmOpen: false,
      direction: null,
      branchName: null,
      openConfirm: vi.fn(),
      closeConfirm: vi.fn(),
    }),
}));
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
  "@posthog/ui/features/git-interaction/components/CloudGitInteractionHeader",
  () => ({ CloudGitInteractionHeader: () => <div>cloud actions</div> }),
);
vi.mock(
  "@posthog/ui/features/git-interaction/components/TaskActionsMenu",
  () => ({
    TaskActionsMenu: () => <div>task menu</div>,
  }),
);
vi.mock("@posthog/ui/features/sessions/components/StopCloudRunButton", () => ({
  StopCloudRunButton: () => <div>stop cloud run</div>,
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
  render(
    <Theme>
      <TaskHeaderActions task={task} />
    </Theme>,
  );
}

describe("TaskHeaderActions", () => {
  it("does not show workspace-dependent actions before workspaces load", () => {
    useWorkspace.mockReturnValue(null);
    useWorkspaceLoaded.mockReturnValue(false);

    renderActions();

    expect(screen.queryByText("Continue in cloud")).not.toBeInTheDocument();
    expect(screen.queryByText("task menu")).not.toBeInTheDocument();
  });

  it("shows cloud controls for a loaded cloud workspace", () => {
    useWorkspace.mockReturnValue({ mode: "cloud" });
    useWorkspaceLoaded.mockReturnValue(true);

    renderActions();

    expect(screen.getByText("stop cloud run")).toBeInTheDocument();
    expect(screen.getByText("cloud actions")).toBeInTheDocument();
    expect(screen.getByText("task menu")).toBeInTheDocument();
    expect(screen.queryByText("Continue in cloud")).not.toBeInTheDocument();
  });

  it("shows cloud controls for a cloud run without a local workspace row", () => {
    useWorkspace.mockReturnValue(null);
    useWorkspaceLoaded.mockReturnValue(true);

    renderActions({
      id: "task-1",
      title: "Fix the bug",
      latest_run: { environment: "cloud" },
    } as Task);

    expect(screen.getByText("stop cloud run")).toBeInTheDocument();
    expect(screen.getByText("cloud actions")).toBeInTheDocument();
    expect(screen.queryByText("Continue in cloud")).not.toBeInTheDocument();
  });
});
