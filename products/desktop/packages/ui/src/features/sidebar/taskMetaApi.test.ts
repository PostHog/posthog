import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  activeTarget: vi.fn(),
  hasFocus: vi.fn(),
  invalidateQueries: vi.fn(),
  markActivity: vi.fn(),
  markViewed: vi.fn(),
}));

vi.mock("@posthog/di/container", () => ({
  resolveService: (token: symbol) => {
    switch (token.description) {
      case "posthog.host.trpcClient":
        return {
          workspace: {
            markActivity: { mutate: mocks.markActivity },
            markViewed: { mutate: mocks.markViewed },
          },
        };
      case "posthog.ui.ImperativeQueryClient":
        return { invalidateQueries: mocks.invalidateQueries };
      case "posthog.ui.notifications.activeView":
        return {
          getActiveTarget: mocks.activeTarget,
          hasFocus: mocks.hasFocus,
        };
      default:
        throw new Error(`Unexpected service: ${token.description}`);
    }
  },
}));

import { taskViewedApi } from "./taskMetaApi";

describe("taskViewedApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.markActivity.mockResolvedValue(undefined);
    mocks.markViewed.mockResolvedValue(undefined);
  });

  it.each([
    ["the focused task is open", true, "task-1", 1],
    ["the app is unfocused", false, "task-1", 0],
    ["a different task is open", true, "task-2", 0],
  ])(
    "updates viewed state when %s",
    async (_label, hasFocus, activeTaskId, expectedViewedCalls) => {
      mocks.hasFocus.mockReturnValue(hasFocus);
      mocks.activeTarget.mockReturnValue({
        kind: "task",
        taskId: activeTaskId,
      });

      taskViewedApi.markActivity("task-1");

      await vi.waitFor(() => {
        expect(mocks.invalidateQueries).toHaveBeenCalledOnce();
      });
      expect(mocks.markActivity).toHaveBeenCalledWith({ taskId: "task-1" });
      expect(mocks.markViewed).toHaveBeenCalledTimes(expectedViewedCalls);
    },
  );
});
