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

  // Shares the mutation scope with togglePin so a bulk write and a single-row
  // toggle queue behind each other instead of racing on the same cache entry.
  const setPinnedManyMutation = useMutation({
    scope: { id: "task-pins" },
    mutationFn: async ({
      taskIds,
      pinned,
    }: {
      taskIds: string[];
      pinned: boolean;
    }) => {
      const results = await Promise.allSettled(
        taskIds.map((taskId) => pinnedTasksApi.setPinned(taskId, pinned)),
      );
      return {
        succeeded: taskIds.filter((_, i) => results[i].status === "fulfilled"),
        failed: taskIds.filter((_, i) => results[i].status === "rejected"),
      };
    },
    onMutate: async ({ taskIds, pinned }) => {
      await queryClient.cancelQueries({ queryKey: pinnedQueryKey });
      queryClient.setQueryData<string[]>(pinnedQueryKey, (old) => {
        const batch = new Set(taskIds);
        const rest = old?.filter((id) => !batch.has(id)) ?? [];
        return pinned ? [...rest, ...taskIds] : rest;
      });
    },
    // No onError rollback: the mutationFn settles every request itself and
    // never rejects, so partial failure is reconciled here instead — undo the
    // optimistic write for whichever ids didn't make it.
    onSuccess: ({ failed }, { pinned }) => {
      if (failed.length === 0) return;
      const rolledBack = new Set(failed);
      queryClient.setQueryData<string[]>(pinnedQueryKey, (old) => {
        const rest = old?.filter((id) => !rolledBack.has(id)) ?? [];
        return pinned ? rest : [...rest, ...failed];
      });
    },
  });

  const setPinnedManyMutationRef = useRef(setPinnedManyMutation);
  setPinnedManyMutationRef.current = setPinnedManyMutation;

  const setPinnedMany = useCallback(
    async (taskIds: string[], pinned: boolean) => {
      const nextPinnedSet = new Set(pinnedSetRef.current);
      for (const taskId of taskIds) {
        if (pinned) nextPinnedSet.add(taskId);
        else nextPinnedSet.delete(taskId);
      }
      pinnedSetRef.current = nextPinnedSet;
      return setPinnedManyMutationRef.current.mutateAsync({ taskIds, pinned });
    },
    [],
  );

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
    setPinnedMany,
    isSettingPinnedMany: setPinnedManyMutation.isPending,
    unpin,
    isPinned,
  };
}
