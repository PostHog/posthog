import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

const NO_WORKTREES: never[] = [];

/** Task-less linked worktrees of a repo the sidebar offers to start a task in. */
export function useAdoptableWorktrees(mainRepoPath: string) {
  const trpc = useHostTRPC();
  const { data } = useQuery(
    trpc.workspace.listAdoptableWorktrees.queryOptions(
      { mainRepoPath },
      { staleTime: 30_000 },
    ),
  );
  return data ?? NO_WORKTREES;
}
