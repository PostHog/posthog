import { useHostTRPC } from "@posthog/host-router/react";
import type { Workspace } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  type QueryClient,
  QueryObserver,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useMemo, useSyncExternalStore } from "react";

type HostTRPC = ReturnType<typeof useHostTRPC>;

function createWorkspacesObserver(queryClient: QueryClient, trpc: HostTRPC) {
  return new QueryObserver(
    queryClient,
    trpc.workspace.getAll.queryOptions(undefined, {
      staleTime: 1000 * 60,
      // The bare observer never tracks accessed fields the way `useQuery` does,
      // so without this it notifies every subscriber on any result change
      // (fetchStatus flips, dataUpdatedAt bumps on refetch). All hooks here read
      // only these two fields.
      notifyOnChangeProps: ["data", "isFetched"],
    }),
  );
}

type WorkspacesObserver = ReturnType<typeof createWorkspacesObserver>;

// Dozens of rows and panels read this map. One observer per query client,
// shared by every consumer, keeps their mount from creating a QueryObserver each.
const observers = new WeakMap<QueryClient, WorkspacesObserver>();

function useWorkspacesQuery(): ReturnType<
  WorkspacesObserver["getCurrentResult"]
> {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  let observer = observers.get(queryClient);
  if (!observer) {
    observer = createWorkspacesObserver(queryClient, trpc);
    observers.set(queryClient, observer);
  }
  const shared = observer;
  const subscribe = useCallback(
    (onChange: () => void) => shared.subscribe(onChange),
    [shared],
  );
  const getSnapshot = useCallback(() => shared.getCurrentResult(), [shared]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
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

// The workspace row is the local source of truth for the active execution mode.
export function isCloudTask(task: Task, workspace: Workspace | null): boolean {
  if (workspace) {
    return workspace.mode === "cloud";
  }
  return task.latest_run?.environment === "cloud";
}

export function useIsCloudTask(task: Task): boolean {
  const workspace = useWorkspace(task.id);
  return isCloudTask(task, workspace);
}

export function useWorkspaceLoaded(): boolean {
  const { isFetched } = useWorkspacesQuery();
  return isFetched;
}
