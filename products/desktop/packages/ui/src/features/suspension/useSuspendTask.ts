import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { useFocusStore } from "@posthog/ui/features/focus/focusStore";
import { destroyTaskTerminals } from "@posthog/ui/features/terminal/destroyTaskTerminals";
import { logger } from "@posthog/ui/shell/logger";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { WORKSPACE_QUERY_KEY } from "../workspace/identifiers";

const log = logger.scope("suspend-task");

interface SuspendTaskInput {
  taskId: string;
  reason?: "manual" | "max_worktrees" | "inactivity";
}

export function useSuspendTask() {
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();

  const suspendedTaskIdsKey = trpc.suspension.suspendedTaskIds.queryKey();
  const suspensionPathKey = trpc.suspension.pathFilter().queryKey;
  const suspendMutation = useMutation(
    trpc.suspension.suspend.mutationOptions(),
  );

  const suspendTask = async (input: SuspendTaskInput) => {
    const { taskId, reason = "manual" } = input;
    const focusStore = useFocusStore.getState();
    const workspaces = await hostClient.workspace.getAll.query();
    const workspace = workspaces[taskId] ?? null;

    queryClient.setQueryData<string[]>(suspendedTaskIdsKey, (old) =>
      old ? [...old, taskId] : [taskId],
    );

    if (
      workspace?.worktreePath &&
      focusStore.session?.worktreePath === workspace.worktreePath
    ) {
      log.info("Unfocusing workspace before suspending");
      await focusStore.disableFocus();
    }

    try {
      await suspendMutation.mutateAsync({ taskId, reason });

      destroyTaskTerminals(taskId);
      queryClient.invalidateQueries({ queryKey: suspensionPathKey });
      queryClient.invalidateQueries({ queryKey: suspendedTaskIdsKey });
      queryClient.invalidateQueries({ queryKey: WORKSPACE_QUERY_KEY });
    } catch (error) {
      log.error("Failed to suspend task", error);

      queryClient.setQueryData<string[]>(suspendedTaskIdsKey, (old) =>
        old ? old.filter((id) => id !== taskId) : [],
      );

      throw error;
    }
  };

  return { suspendTask };
}
