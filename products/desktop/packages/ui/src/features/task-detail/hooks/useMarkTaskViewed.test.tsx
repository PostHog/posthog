import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const taskViewed = vi.hoisted(() => ({
  markAsViewed: vi.fn(),
}));

vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => taskViewed,
}));

import { useMarkTaskViewed } from "./useMarkTaskViewed";

describe("useMarkTaskViewed", () => {
  beforeEach(() => vi.clearAllMocks());

  it("marks only when the task id changes and uses its latest activity", () => {
    const { rerender } = renderHook(
      ({ taskId, activityAtMs }) => useMarkTaskViewed(taskId, activityAtMs),
      {
        initialProps: { taskId: "task-1", activityAtMs: 1_000 },
      },
    );

    expect(taskViewed.markAsViewed).toHaveBeenLastCalledWith("task-1", 1_000);

    taskViewed.markAsViewed.mockClear();
    rerender({ taskId: "task-1", activityAtMs: 2_000 });
    expect(taskViewed.markAsViewed).not.toHaveBeenCalled();

    rerender({ taskId: "task-2", activityAtMs: 3_000 });
    expect(taskViewed.markAsViewed).toHaveBeenLastCalledWith("task-2", 3_000);
  });
});
