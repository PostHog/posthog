import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

export type SidebarPrState = "merged" | "open" | "draft" | "closed" | null;

export interface TaskPrStatus {
  prState: SidebarPrState;
  hasDiff: boolean;
}

const SIDEBAR_STALE_TIME = 60_000;
const EMPTY: TaskPrStatus = { prState: null, hasDiff: false };

export function useTaskPrStatus(task: {
  id: string;
  cloudPrUrl?: string | null;
  taskRunEnvironment?: string | null;
}): TaskPrStatus {
  const trpc = useHostTRPC();

  const skipQuery = task.taskRunEnvironment === "cloud" && !task.cloudPrUrl;

  const { data } = useQuery(
    trpc.workspace.getTaskPrStatus.queryOptions(
      { taskId: task.id, cloudPrUrl: task.cloudPrUrl ?? null },
      {
        staleTime: SIDEBAR_STALE_TIME,
        placeholderData: (prev) => prev,
        enabled: !skipQuery,
      },
    ),
  );

  if (!data || (!data.prState && !data.hasDiff)) return EMPTY;
  return data;
}
