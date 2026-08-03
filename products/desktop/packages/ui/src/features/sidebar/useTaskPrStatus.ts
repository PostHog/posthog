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

  // No id means no task — canvas rows share this hook — and a cloud run with no
  // PR url yet has nothing to look up either. Both would spend a round trip to
  // be told nothing.
  const skipQuery =
    !task.id || (task.taskRunEnvironment === "cloud" && !task.cloudPrUrl);

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
