import {
  parseTimestamps,
  type TaskTimestamps,
} from "@posthog/core/sidebar/taskMeta";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
} from "@posthog/ui/features/notifications/identifiers";
import { routeNotification } from "@posthog/ui/features/notifications/routeNotification";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";

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

function isViewingTask(taskId: string): boolean {
  const view = resolveService<IActiveView>(ACTIVE_VIEW_PROVIDER);
  return (
    routeNotification({
      appFocused: view.hasFocus(),
      viewingTarget: view.getActiveTarget(),
      notificationTarget: { kind: "task", taskId },
    }) === "suppress"
  );
}

async function markActivity(taskId: string): Promise<void> {
  const keepRead = isViewingTask(taskId);
  const api = workspace();
  await api.markActivity.mutate({ taskId });
  if (keepRead) {
    await api.markViewed.mutate({ taskId });
  }
  invalidateTimestamps();
}

export const taskViewedApi = {
  async loadTimestamps(): Promise<Record<string, TaskTimestamps>> {
    return parseTimestamps(await workspace().getAllTaskTimestamps.query());
  },

  markAsViewed(taskId: string): void {
    void workspace().markViewed.mutate({ taskId }).then(invalidateTimestamps);
  },

  markActivity(taskId: string): void {
    void markActivity(taskId);
  },
};

export const pinnedTasksApi = {
  async getPinnedTaskIds(): Promise<string[]> {
    const client = await getAuthenticatedClient();
    if (!client) return [];
    return client.getPinnedTaskIds();
  },

  async setPinned(
    taskId: string,
    pinned: boolean,
  ): Promise<{ taskId: string; isPinned: boolean }> {
    const client = await getAuthenticatedClient();
    if (!client) return { taskId, isPinned: false };
    const isPinned = await client.setTaskPinned(taskId, pinned);
    return { taskId, isPinned };
  },

  async unpin(taskId: string): Promise<void> {
    const client = await getAuthenticatedClient();
    if (client) await client.setTaskPinned(taskId, false);
  },

  isPinned(pinnedTaskIds: Set<string>, taskId: string): boolean {
    return pinnedTaskIds.has(taskId);
  },
};
