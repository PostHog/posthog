import {
  buildCreateWorkspaceRequest,
  selectExistingWorkspace,
} from "@posthog/core/workspace/ensureWorkspace";
import { useHostTRPC } from "@posthog/host-router/react";
import type { Workspace, WorkspaceMode } from "@posthog/shared";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

function useInvalidateWorkspaceCaches() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  return useCallback(
    async (mainRepoPath?: string) => {
      const tasks: Promise<void>[] = [
        queryClient.invalidateQueries({
          queryKey: trpc.workspace.getAll.queryKey(),
        }),
      ];
      if (mainRepoPath) {
        tasks.push(
          queryClient.invalidateQueries(
            trpc.workspace.listGitWorktrees.queryFilter({ mainRepoPath }),
          ),
        );
      }
      await Promise.all(tasks);
    },
    [queryClient, trpc],
  );
}

export function useCreateWorkspace(): { isPending: boolean } {
  const trpc = useHostTRPC();
  const invalidateCaches = useInvalidateWorkspaceCaches();

  const mutation = useMutation(
    trpc.workspace.create.mutationOptions({
      onSuccess: (_data, variables) => {
        void invalidateCaches(variables.mainRepoPath);
      },
    }),
  );

  return { isPending: mutation.isPending };
}

export function useDeleteWorkspace(): { isPending: boolean } {
  const trpc = useHostTRPC();
  const invalidateCaches = useInvalidateWorkspaceCaches();

  const mutation = useMutation(
    trpc.workspace.delete.mutationOptions({
      onSuccess: (_data, variables) => {
        void invalidateCaches(variables.mainRepoPath);
      },
    }),
  );

  return { isPending: mutation.isPending };
}

export function useEnsureWorkspace(): {
  ensureWorkspace: (
    taskId: string,
    repoPath: string,
    mode?: WorkspaceMode,
    branch?: string | null,
  ) => Promise<Workspace | null>;
  isCreating: boolean;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const invalidateCaches = useInvalidateWorkspaceCaches();

  const createMutation = useMutation(
    trpc.workspace.create.mutationOptions({
      onSuccess: (_data, variables) => {
        void invalidateCaches(variables.mainRepoPath);
      },
    }),
  );

  const ensureWorkspace = useCallback(
    async (
      taskId: string,
      repoPath: string,
      mode: WorkspaceMode = "worktree",
      branch?: string | null,
    ): Promise<Workspace | null> => {
      const workspacesKey = trpc.workspace.getAll.queryKey();
      const existing = selectExistingWorkspace(
        queryClient.getQueryData<Record<string, Workspace>>(workspacesKey),
        taskId,
      );
      if (existing) {
        return existing;
      }

      const result = await createMutation.mutateAsync(
        buildCreateWorkspaceRequest(taskId, repoPath, mode, branch),
      );

      if (!result) {
        throw new Error("Failed to create workspace");
      }

      await invalidateCaches(repoPath);
      return selectExistingWorkspace(
        queryClient.getQueryData<Record<string, Workspace>>(workspacesKey),
        taskId,
      );
    },
    [createMutation, queryClient, invalidateCaches, trpc],
  );

  return {
    ensureWorkspace,
    isCreating: createMutation.isPending,
  };
}
