import { useHostTRPC } from "@posthog/host-router/react";
import type { Workspace } from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

function useWorkspacesQuery() {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.workspace.getAll.queryOptions(undefined, {
      staleTime: 1000 * 60,
    }),
  );
}

export function useWorkspaces(): {
  data: Record<string, Workspace> | undefined;
  isFetched: boolean;
} {
  const query = useWorkspacesQuery();
  return { data: query.data, isFetched: query.isFetched };
}

export function useWorkspace(taskId: string | undefined): Workspace | null {
  const { data: workspaces } = useWorkspacesQuery();
  return useMemo(
    () => workspaces?.[taskId ?? ""] ?? null,
    [workspaces, taskId],
  );
}

export function useIsWorkspaceCloudRun(taskId: string | undefined): boolean {
  const workspace = useWorkspace(taskId);
  return workspace?.mode === "cloud";
}

export function useWorkspaceLoaded(): boolean {
  const { isFetched } = useWorkspacesQuery();
  return isFetched;
}
