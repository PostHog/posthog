import type { Task } from "@posthog/shared/domain-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const ACTIVITY_AT = "2026-07-17T12:00:00.000Z";
const taskViewed = vi.hoisted(() => ({
  timestamps: {} as Record<
    string,
    { lastViewedAt: number | null; lastActivityAt: number | null }
  >,
  markAsViewed: vi.fn(),
  markAsUnread: vi.fn(),
}));

vi.mock("@posthog/di/react", () => ({ useService: () => ({}) }));
vi.mock("@posthog/ui/features/sessions/useSession", () => ({
  useSessionSelector: () => ({
    isCloud: false,
    cloudStatus: null,
    stopRequested: false,
    taskRunId: null,
    supportsSummary: false,
  }),
}));
vi.mock("@posthog/ui/features/sessions/sideQuestionStore", () => ({
  useSideQuestionStore: (selector: (state: { byTaskId: object }) => unknown) =>
    selector({ byTaskId: {} }),
}));
vi.mock("@posthog/ui/features/archive/useTaskArchive", () => ({
  useTaskArchive: () => ({ requestArchive: vi.fn(), dialog: null }),
}));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => taskViewed,
}));
vi.mock("@posthog/ui/features/sessions/components/StopCloudRunDialog", () => ({
  StopCloudRunDialog: () => null,
}));

import { TaskOverflowMenu } from "./TaskOverflowMenu";

const task = {
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Investigate signup drop-off",
  description: "",
  created_at: ACTIVITY_AT,
  updated_at: ACTIVITY_AT,
  origin_product: "user_created",
} satisfies Task;

describe("TaskOverflowMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    taskViewed.timestamps = {};
  });

  it.each([
    { unread: false, label: "Mark as unread", state: "read" },
    { unread: true, label: "Mark as read", state: "unread" },
  ])("offers $label for a $state session", async ({ unread, label }) => {
    const activityAtMs = Date.parse(ACTIVITY_AT);
    taskViewed.timestamps = {
      [task.id]: {
        lastViewedAt: unread ? activityAtMs - 1 : activityAtMs,
        lastActivityAt: null,
      },
    };
    const user = userEvent.setup();
    render(<TaskOverflowMenu task={task} />);

    fireEvent.mouseDown(screen.getByRole("button", { name: "Task actions" }), {
      button: 0,
    });
    await waitFor(() => expect(screen.getByText(label)).toBeInTheDocument());
    await user.click(screen.getByText(label));

    if (unread) {
      expect(taskViewed.markAsViewed).toHaveBeenCalledWith(
        task.id,
        activityAtMs,
      );
      expect(taskViewed.markAsUnread).not.toHaveBeenCalled();
    } else {
      expect(taskViewed.markAsUnread).toHaveBeenCalledWith(
        task.id,
        activityAtMs,
      );
      expect(taskViewed.markAsViewed).not.toHaveBeenCalled();
    }
  });
});
