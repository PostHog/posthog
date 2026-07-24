import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";

export function usePinnedTasks() {
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  const pinnedQueryKey = trpc.workspace.getPinnedTaskIds.queryKey();

  const { data: pinnedTaskIds = [], isLoading } = useQuery(
    trpc.workspace.getPinnedTaskIds.queryOptions(undefined, {
      staleTime: 30_000,
    }),
  );

  const pinnedSet = useMemo(() => new Set(pinnedTaskIds), [pinnedTaskIds]);

  const togglePinMutation = useMutation({
    mutationFn: ({ taskId }: { taskId: string }) =>
      hostClient.workspace.togglePin.mutate({ taskId }),
    onMutate: async ({ taskId }) => {
      await queryClient.cancelQueries({ queryKey: pinnedQueryKey });
      const previous = queryClient.getQueryData<string[]>(pinnedQueryKey);
      const wasPinned = previous?.includes(taskId);
      queryClient.setQueryData<string[]>(pinnedQueryKey, (old) => {
        if (!old) return wasPinned ? [] : [taskId];
        return wasPinned ? old.filter((id) => id !== taskId) : [...old, taskId];
      });
      return { previous, wasPinned, taskId };
    },
    onError: (_, __, context) => {
      if (context?.previous) {
        queryClient.setQueryData(pinnedQueryKey, context.previous);
      }
    },
    onSuccess: (result, _, context) => {
      const taskId = context?.taskId;
      if (!taskId) return;
      queryClient.setQueryData<string[]>(pinnedQueryKey, (old) => {
        if (!old) return result.isPinned ? [taskId] : [];
        const filtered = old.filter((id) => id !== taskId);
        return result.isPinned ? [...filtered, taskId] : filtered;
      });
    },
  });

  const togglePinMutationRef = useRef(togglePinMutation);
  togglePinMutationRef.current = togglePinMutation;

  const pinnedSetRef = useRef(pinnedSet);
  pinnedSetRef.current = pinnedSet;

  const togglePin = useCallback(async (taskId: string) => {
    await togglePinMutationRef.current.mutateAsync({ taskId });
  }, []);

  const unpin = useCallback(async (taskId: string) => {
    if (!pinnedSetRef.current.has(taskId)) return;
    const result = await togglePinMutationRef.current.mutateAsync({ taskId });
    if (result.isPinned) {
      await togglePinMutationRef.current.mutateAsync({ taskId });
    }
  }, []);

  const isPinned = useCallback(
    (taskId: string) => pinnedSet.has(taskId),
    [pinnedSet],
  );

  return {
    pinnedTaskIds: pinnedSet,
    isLoading,
    togglePin,
    unpin,
    isPinned,
  };
}
