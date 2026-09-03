import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const markAsViewed = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ markAsViewed }),
}));

import { useMarkTaskViewed } from "./useMarkTaskViewed";

describe("useMarkTaskViewed", () => {
  beforeEach(() => vi.clearAllMocks());

  it("marks a rendered task viewed through its activity timestamp", () => {
    const task = {
      id: "task-1",
      created_at: "2026-09-03T09:00:00.000Z",
      updated_at: "2026-09-03T12:00:00.000Z",
      last_activity_at: "2026-09-03T10:00:00.000Z",
    };

    const { rerender } = renderHook(
      ({ lastActivityAt }) =>
        useMarkTaskViewed({
          ...task,
          last_activity_at: lastActivityAt,
        }),
      { initialProps: { lastActivityAt: task.last_activity_at } },
    );

    expect(markAsViewed).toHaveBeenLastCalledWith(
      "task-1",
      task.last_activity_at,
    );

    const nextActivityAt = "2026-09-03T11:00:00.000Z";
    rerender({ lastActivityAt: nextActivityAt });
    expect(markAsViewed).toHaveBeenLastCalledWith("task-1", nextActivityAt);
  });
});
