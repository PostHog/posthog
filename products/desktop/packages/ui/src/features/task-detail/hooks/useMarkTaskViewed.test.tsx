import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const markAsViewed = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ markAsViewed }),
}));

import { useMarkTaskViewed } from "./useMarkTaskViewed";

describe("useMarkTaskViewed", () => {
  beforeEach(() => vi.clearAllMocks());

  it("marks each rendered task as viewed once", () => {
    const { rerender } = renderHook((taskId) => useMarkTaskViewed(taskId), {
      initialProps: "task-1",
    });

    expect(markAsViewed).toHaveBeenLastCalledWith("task-1");

    markAsViewed.mockClear();
    rerender("task-1");
    expect(markAsViewed).not.toHaveBeenCalled();

    rerender("task-2");
    expect(markAsViewed).toHaveBeenLastCalledWith("task-2");
  });
});
