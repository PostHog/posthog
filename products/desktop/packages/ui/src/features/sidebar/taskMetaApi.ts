import {
  parseTimestamps,
  type TaskTimestamps,
} from "@posthog/core/sidebar/taskMeta";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";

export type { TaskTimestamps };

// Outer array partial-matches tRPC's `[["workspace", "getAllTaskTimestamps"], { type }]`.
const TASK_TIMESTAMPS_QUERY_KEY = [["workspace", "getAllTaskTimestamps"]];

function workspace() {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT).workspace;
}

function invalidateTimestamps(): void {
  void resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  ).invalidateQueries({ queryKey: TASK_TIMESTAMPS_QUERY_KEY });
}

export const taskViewedApi = {
  async loadTimestamps(): Promise<Record<string, TaskTimestamps>> {
    return parseTimestamps(await workspace().getAllTaskTimestamps.query());
  },

  markAsViewed(taskId: string): void {
    void workspace().markViewed.mutate({ taskId }).then(invalidateTimestamps);
  },

  markActivity(taskId: string): void {
    void workspace().markActivity.mutate({ taskId }).then(invalidateTimestamps);
  },
};

export const pinnedTasksApi = {
  async getPinnedTaskIds(): Promise<string[]> {
    return workspace().getPinnedTaskIds.query();
  },

  async togglePin(
    taskId: string,
  ): Promise<{ taskId: string; isPinned: boolean }> {
    const result = await workspace().togglePin.mutate({ taskId });
    return { taskId, isPinned: result.isPinned };
  },

  async unpin(taskId: string): Promise<void> {
    const result = await workspace().togglePin.mutate({ taskId });
    if (result.isPinned) {
      await workspace().togglePin.mutate({ taskId });
    }
  },

  isPinned(pinnedTaskIds: Set<string>, taskId: string): boolean {
    return pinnedTaskIds.has(taskId);
  },
};
