import type { Task } from "@posthog/shared/domain-types";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The status comes from live session/workspace state and a per-task tRPC query,
// none of which a unit test has. Stubbed at the module boundary, as
// ChannelItemRow.test.tsx does for the same reason.
const mocks = vi.hoisted(() => ({
  bluebird: true,
  status: null as TaskStatusInput | null,
}));
vi.mock("@posthog/ui/features/feature-flags/useBluebirdFlag", () => ({
  useBluebirdFlag: () => mocks.bluebird,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useTaskStatusInput: () => mocks.status,
}));

import { TaskHeaderBadges, TaskHeaderMark } from "./TaskHeaderStatus";

const task = { id: "task-1" } as Task;

function renderMark() {
  return render(
    <Theme>
      <TaskHeaderMark task={task} mode="cloud" />
    </Theme>,
  );
}

describe("TaskHeaderStatus", () => {
  beforeEach(() => {
    mocks.bluebird = true;
    mocks.status = { workspaceMode: "cloud" };
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
    const { rerender } = render(
      <Theme>
        <TaskHeaderBadges task={task} />
      </Theme>,
    );

    expect(screen.getByRole("img", { name: "Local" })).toBeInTheDocument();

    mocks.status = { workspaceMode: "cloud" };
    rerender(
      <Theme>
        <TaskHeaderBadges task={task} />
      </Theme>,
    );

    expect(
      screen.queryByRole("img", { name: "Local" }),
    ).not.toBeInTheDocument();
  });
});
