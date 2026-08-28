import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The record-present branches render heavy session/composer trees this test
// never exercises (both cases below have no record), so stub them out.
vi.mock("../../sessions/components/PendingChatView", () => ({
  PendingChatView: () => <div>pending-chat</div>,
}));
vi.mock("./InterruptedPromptView", () => ({
  InterruptedPromptView: () => <div>interrupted</div>,
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTaskInput: vi.fn(),
}));
vi.mock("@posthog/ui/features/task-detail/pendingPromptActions", () => ({
  recoverPendingPrompt: vi.fn(),
  discardPendingPrompt: vi.fn(),
}));

import { usePendingTaskPromptStore } from "../../../shell/pendingTaskPromptStore";
import { TaskPendingView } from "./TaskPendingView";

const UNAVAILABLE_TEXT = "This prompt is no longer available";

function renderPending() {
  render(
    <Theme>
      <TaskPendingView pendingTaskKey="missing-key" />
    </Theme>,
  );
}

describe("TaskPendingView hydration gate", () => {
  beforeEach(() => {
    usePendingTaskPromptStore.setState({ byKey: {}, _hasHydrated: false });
  });

  // The store hydrates from async host storage, so a lookup miss before
  // hydration does not mean the record is gone. Showing the unavailable state
  // then would strand a still-on-disk prompt behind a "Start a new task" button.
  it("waits instead of claiming the prompt is gone before hydration", () => {
    usePendingTaskPromptStore.setState({ _hasHydrated: false });
    renderPending();
    expect(screen.queryByText(UNAVAILABLE_TEXT)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Start a new task" }),
    ).not.toBeInTheDocument();
  });

  it("shows the unavailable state once a hydrated lookup finds no record", () => {
    usePendingTaskPromptStore.setState({ _hasHydrated: true });
    renderPending();
    expect(screen.getByText(UNAVAILABLE_TEXT)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Start a new task" }),
    ).toBeInTheDocument();
  });
});
