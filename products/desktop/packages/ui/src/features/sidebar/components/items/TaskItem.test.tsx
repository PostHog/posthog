import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TaskItem } from "./TaskItem";

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToPullRequestView: vi.fn(),
}));

function renderTaskItem(props: { subtitle?: string } = {}) {
  return render(
    <TaskItem
      taskId="task-1"
      label="Write runbook for 5xx errors"
      isActive={false}
      onClick={() => {}}
      onContextMenu={() => {}}
      {...props}
    />,
  );
}

describe("TaskItem", () => {
  it("renders the context line under the title when given one", () => {
    renderTaskItem({ subtitle: "code · posthog-code/fix-login" });

    expect(
      screen.getByText("code · posthog-code/fix-login"),
    ).toBeInTheDocument();
  });

  it("stays a single line when there is no context to show", () => {
    renderTaskItem();

    // Only the title renders — rows inside a repository group already get their
    // repository from the group header, so they must not grow a second line.
    expect(
      screen.getByText("Write runbook for 5xx errors"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button").textContent).toBe(
      "Write runbook for 5xx errors",
    );
  });
});
