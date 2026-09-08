import {
  parseTimestamps,
  type RawTaskTimestamp,
} from "@posthog/core/sidebar/taskMeta";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";

const taskMutationQueues = new Map<string, Promise<void>>();

async function waitForTaskMutationQueue(taskId: string): Promise<void> {
  let continuation = taskMutationQueues.get(taskId);
  while (continuation) {
    await continuation;
    const currentContinuation = taskMutationQueues.get(taskId);
    if (!currentContinuation || currentContinuation === continuation) {
      return;
    }
    continuation = currentContinuation;
  }
}

function enqueueTaskMutation<Result>(
  taskId: string,
  request: () => Promise<Result>,
): Promise<Result> {
  const previousRequest = taskMutationQueues.get(taskId) ?? Promise.resolve();
  const requestPromise = previousRequest.then(request);
  const continuation = requestPromise.then(
    () => undefined,
    () => undefined,
  );
  taskMutationQueues.set(taskId, continuation);
  void continuation.then(() => {
    if (taskMutationQueues.get(taskId) === continuation) {
      taskMutationQueues.delete(taskId);
    }
  });
  return requestPromise;
}

export function useTaskViewed() {
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  const timestampsQueryKey = trpc.workspace.getAllTaskTimestamps.queryKey();

  const { data: rawTimestamps = {}, isLoading } = useQuery(
    trpc.workspace.getAllTaskTimestamps.queryOptions(undefined, {
      staleTime: 30_000,
    }),
  );

  const timestamps = useMemo(
    () => parseTimestamps(rawTimestamps),
    [rawTimestamps],
  );

  const markViewedMutation = useMutation({
    mutationFn: ({
      taskId,
      activityAtMs,
    }: {
      taskId: string;
      activityAtMs?: number;
    }) =>
      enqueueTaskMutation(taskId, () =>
        hostClient.workspace.markViewed.mutate(
          activityAtMs === undefined ? { taskId } : { taskId, activityAtMs },
        ),
      ),
    onMutate: async ({ taskId, activityAtMs }) => {
      await queryClient.cancelQueries({ queryKey: timestampsQueryKey });
      const storedActivityAt =
        queryClient.getQueryData<Record<string, RawTaskTimestamp>>(
          timestampsQueryKey,
        )?.[taskId]?.lastActivityAt;
      const storedActivityAtMs = storedActivityAt
        ? Date.parse(storedActivityAt)
        : 0;
      const optimisticLastViewedAt = new Date(
        Math.max(
          Date.now(),
          activityAtMs ?? 0,
          Number.isFinite(storedActivityAtMs) ? storedActivityAtMs : 0,
        ),
      ).toISOString();
      queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
        timestampsQueryKey,
        (old) => ({
          ...old,
          [taskId]: {
            pinnedAt: old?.[taskId]?.pinnedAt ?? null,
            lastViewedAt: optimisticLastViewedAt,
            lastActivityAt: old?.[taskId]?.lastActivityAt ?? null,
          },
        }),
      );
    },
    onError: async (_, { taskId }) => {
      await waitForTaskMutationQueue(taskId);
      await queryClient.invalidateQueries({ queryKey: timestampsQueryKey });
    },
  });

  const markUnreadMutation = useMutation({
    mutationFn: ({
      taskId,
      activityAtMs,
    }: {
      taskId: string;
      activityAtMs: number;
    }) =>
      enqueueTaskMutation(taskId, () =>
        hostClient.workspace.markUnread.mutate({ taskId, activityAtMs }),
      ),
    onMutate: async ({ taskId, activityAtMs }) => {
      await queryClient.cancelQueries({ queryKey: timestampsQueryKey });
      const storedActivityAt =
        queryClient.getQueryData<Record<string, RawTaskTimestamp>>(
          timestampsQueryKey,
        )?.[taskId]?.lastActivityAt;
      const storedActivityAtMs = storedActivityAt
        ? new Date(storedActivityAt).getTime()
        : 0;
      const effectiveActivityAtMs = Math.max(
        activityAtMs,
        Number.isFinite(storedActivityAtMs) ? storedActivityAtMs : 0,
      );
      const optimisticLastViewedAt = new Date(
        effectiveActivityAtMs - 1,
      ).toISOString();
      queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
        timestampsQueryKey,
        (old) => ({
          ...old,
          [taskId]: {
            pinnedAt: old?.[taskId]?.pinnedAt ?? null,
            lastActivityAt: old?.[taskId]?.lastActivityAt ?? null,
            lastViewedAt: optimisticLastViewedAt,
          },
        }),
      );
    },
    onError: async (_, { taskId }) => {
      await waitForTaskMutationQueue(taskId);
      await queryClient.invalidateQueries({ queryKey: timestampsQueryKey });
    },
  });

  const markActivityMutation = useMutation({
    mutationFn: ({ taskId }: { taskId: string }) =>
      enqueueTaskMutation(taskId, () =>
        hostClient.workspace.markActivity.mutate({ taskId }),
      ),
    onMutate: async ({ taskId }) => {
      await queryClient.cancelQueries({ queryKey: timestampsQueryKey });
      const previousLastViewedAt =
        queryClient.getQueryData<Record<string, RawTaskTimestamp>>(
          timestampsQueryKey,
        )?.[taskId]?.lastViewedAt;
      const lastViewedAt = previousLastViewedAt
        ? new Date(previousLastViewedAt).getTime()
        : 0;
      const now = Date.now();
      const activityTime = Math.max(now, lastViewedAt + 1);
      const optimisticLastActivityAt = new Date(activityTime).toISOString();
      queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
        timestampsQueryKey,
        (old) => ({
          ...old,
          [taskId]: {
            pinnedAt: old?.[taskId]?.pinnedAt ?? null,
            lastViewedAt: old?.[taskId]?.lastViewedAt ?? null,
            lastActivityAt: optimisticLastActivityAt,
          },
        }),
      );
    },
    onError: async (_, { taskId }) => {
      await waitForTaskMutationQueue(taskId);
      await queryClient.invalidateQueries({ queryKey: timestampsQueryKey });
    },
  });

  const markViewedMutationRef = useRef(markViewedMutation);
  markViewedMutationRef.current = markViewedMutation;

  const markUnreadMutationRef = useRef(markUnreadMutation);
  markUnreadMutationRef.current = markUnreadMutation;

  const markActivityMutationRef = useRef(markActivityMutation);
  markActivityMutationRef.current = markActivityMutation;

  const markAsViewed = useCallback((taskId: string, activityAtMs?: number) => {
    markViewedMutationRef.current.mutate({ taskId, activityAtMs });
  }, []);

  const markAsUnread = useCallback((taskId: string, activityAtMs: number) => {
    markUnreadMutationRef.current.mutate({ taskId, activityAtMs });
  }, []);

  const markActivity = useCallback((taskId: string) => {
    markActivityMutationRef.current.mutate({ taskId });
  }, []);

  const getLastViewedAt = useCallback(
    (taskId: string) => timestamps[taskId]?.lastViewedAt ?? undefined,
    [timestamps],
  );

  const getLastActivityAt = useCallback(
    (taskId: string) => timestamps[taskId]?.lastActivityAt ?? undefined,
    [timestamps],
  );

  return {
    timestamps,
    isLoading,
    markAsViewed,
    markAsUnread,
    markActivity,
    getLastViewedAt,
    getLastActivityAt,
  };
}
