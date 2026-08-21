import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

export type SidebarPrState = "merged" | "open" | "draft" | "closed" | null;

export interface TaskPrStatus {
  prState: SidebarPrState;
  hasDiff: boolean;
  /** The PR the state belongs to, where the host has one cached for the task. */
  prUrl: string | null;
}

const SIDEBAR_STALE_TIME = 60_000;
const EMPTY: TaskPrStatus = { prState: null, hasDiff: false, prUrl: null };

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

  // A disabled query can retain placeholder data from the previously selected
  // task. Ignore it so a cloud task without a PR never shows stale PR status.
  if (skipQuery || !data) return EMPTY;
  // Nothing to say about the branch, but the url still stands on its own: the
  // host caches it as soon as a PR is opened, and its state stays null whenever
  // the GitHub lookup behind it fails. Dropping it here is what would leave a
  // task that opened a PR showing no sign of one.
  if (!data.prState && !data.hasDiff) return { ...EMPTY, prUrl: data.prUrl };
  return data;
}
