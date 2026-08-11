import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";
import { useAuthenticatedQuery } from "../../hooks/useAuthenticatedQuery";
import { pinnedTasksApi } from "./taskMetaApi";

const PINNED_TASKS_QUERY_KEY = ["task-pins"] as const;

export function usePinnedTasks() {
  const queryClient = useQueryClient();
  const pinnedQueryKey = PINNED_TASKS_QUERY_KEY;

  const { data: pinnedTaskIds = [], isLoading } = useAuthenticatedQuery(
    pinnedQueryKey,
    (client) => client.getPinnedTaskIds(),
    { staleTime: 30_000 },
  );

  const pinnedSet = useMemo(() => new Set(pinnedTaskIds), [pinnedTaskIds]);

  const togglePinMutation = useMutation({
    scope: { id: "task-pins" },
    mutationFn: ({ taskId, pinned }: { taskId: string; pinned: boolean }) =>
      pinnedTasksApi.setPinned(taskId, pinned),
    onMutate: async ({ taskId, pinned }) => {
      await queryClient.cancelQueries({ queryKey: pinnedQueryKey });
      const previous = queryClient.getQueryData<string[]>(pinnedQueryKey);
      const wasPinned = previous?.includes(taskId);
      queryClient.setQueryData<string[]>(pinnedQueryKey, (old) => {
        const filtered = old?.filter((id) => id !== taskId) ?? [];
        return pinned ? [...filtered, taskId] : filtered;
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
    const pinned = !pinnedSetRef.current.has(taskId);
    const nextPinnedSet = new Set(pinnedSetRef.current);
    if (pinned) nextPinnedSet.add(taskId);
    else nextPinnedSet.delete(taskId);
    pinnedSetRef.current = nextPinnedSet;
    await togglePinMutationRef.current.mutateAsync({
      taskId,
      pinned,
    });
  }, []);

  const unpin = useCallback(
    async (taskId: string) => {
      if (!pinnedSetRef.current.has(taskId)) return;
      await pinnedTasksApi.unpin(taskId);
      queryClient.setQueryData<string[]>(pinnedQueryKey, (old) =>
        old?.filter((id) => id !== taskId),
      );
    },
    [queryClient, pinnedQueryKey],
  );

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
