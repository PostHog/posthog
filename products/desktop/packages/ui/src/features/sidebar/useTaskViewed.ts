import {
  parseTimestamps,
  type RawTaskTimestamp,
} from "@posthog/core/sidebar/taskMeta";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";

export function useTaskViewed() {
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  const timestampsQueryKey = trpc.workspace.getAllTaskTimestamps.queryKey();

  const {
    data: rawTimestamps = {},
    isLoading,
    isSuccess: timestampsReady,
  } = useQuery(
    trpc.workspace.getAllTaskTimestamps.queryOptions(undefined, {
      staleTime: 30_000,
    }),
  );

  const timestamps = useMemo(
    () => parseTimestamps(rawTimestamps),
    [rawTimestamps],
  );

  const markViewedMutation = useMutation({
    mutationFn: ({ taskId }: { taskId: string }) =>
      hostClient.workspace.markViewed.mutate({ taskId }),
    onMutate: async ({ taskId }) => {
      await queryClient.cancelQueries({ queryKey: timestampsQueryKey });
      const previous =
        queryClient.getQueryData<Record<string, RawTaskTimestamp>>(
          timestampsQueryKey,
        );
      const now = new Date().toISOString();
      queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
        timestampsQueryKey,
        (old) => {
          if (!old)
            return {
              [taskId]: {
                pinnedAt: null,
                lastViewedAt: now,
                lastActivityAt: null,
              },
            };
          return {
            ...old,
            [taskId]: { ...old[taskId], lastViewedAt: now },
          };
        },
      );
      return { previous };
    },
    onError: (_, __, context) => {
      if (context?.previous) {
        queryClient.setQueryData(timestampsQueryKey, context.previous);
      }
    },
  });

  const markUnreadMutation = useMutation({
    mutationFn: ({
      taskId,
      activityAt,
    }: {
      taskId: string;
      activityAt: number;
    }) => hostClient.workspace.markUnread.mutate({ taskId, activityAt }),
    onMutate: async ({ taskId, activityAt }) => {
      await queryClient.cancelQueries({ queryKey: timestampsQueryKey });
      const previousLastViewedAt =
        queryClient.getQueryData<Record<string, RawTaskTimestamp>>(
          timestampsQueryKey,
        )?.[taskId]?.lastViewedAt ?? null;
      const lastViewedAt = new Date(activityAt - 1).toISOString();
      queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
        timestampsQueryKey,
        (old) => ({
          ...old,
          [taskId]: {
            pinnedAt: old?.[taskId]?.pinnedAt ?? null,
            lastActivityAt: old?.[taskId]?.lastActivityAt ?? null,
            lastViewedAt,
          },
        }),
      );
      return { previousLastViewedAt, lastViewedAt };
    },
    // Roll back only this task's field. Other tasks' updates and a newer view of
    // this task can land while the request is in flight, and must survive.
    onError: (_, { taskId }, context) => {
      if (!context) return;
      queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
        timestampsQueryKey,
        (current) => {
          const entry = current?.[taskId];
          if (!current || entry?.lastViewedAt !== context.lastViewedAt) {
            return current;
          }
          return {
            ...current,
            [taskId]: { ...entry, lastViewedAt: context.previousLastViewedAt },
          };
        },
      );
    },
  });

  const markActivityMutation = useMutation({
    mutationFn: ({ taskId }: { taskId: string }) =>
      hostClient.workspace.markActivity.mutate({ taskId }),
    onMutate: async ({ taskId }) => {
      await queryClient.cancelQueries({ queryKey: timestampsQueryKey });
      const previous =
        queryClient.getQueryData<Record<string, RawTaskTimestamp>>(
          timestampsQueryKey,
        );
      const existing = previous?.[taskId];
      const lastViewedAt = existing?.lastViewedAt
        ? new Date(existing.lastViewedAt).getTime()
        : 0;
      const now = Date.now();
      const activityTime = Math.max(now, lastViewedAt + 1);
      const activityIso = new Date(activityTime).toISOString();
      queryClient.setQueryData<Record<string, RawTaskTimestamp>>(
        timestampsQueryKey,
        (old) => {
          if (!old)
            return {
              [taskId]: {
                pinnedAt: null,
                lastViewedAt: null,
                lastActivityAt: activityIso,
              },
            };
          return {
            ...old,
            [taskId]: { ...old[taskId], lastActivityAt: activityIso },
          };
        },
      );
      return { previous };
    },
    onError: (_, __, context) => {
      if (context?.previous) {
        queryClient.setQueryData(timestampsQueryKey, context.previous);
      }
    },
  });

  const markViewedMutationRef = useRef(markViewedMutation);
  markViewedMutationRef.current = markViewedMutation;

  const markUnreadMutationRef = useRef(markUnreadMutation);
  markUnreadMutationRef.current = markUnreadMutation;

  const markActivityMutationRef = useRef(markActivityMutation);
  markActivityMutationRef.current = markActivityMutation;

  const markAsViewed = useCallback((taskId: string) => {
    markViewedMutationRef.current.mutate({ taskId });
  }, []);

  const markAsUnread = useCallback((taskId: string, activityAt: number) => {
    markUnreadMutationRef.current.mutate({ taskId, activityAt });
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
    timestampsReady,
    isLoading,
    markAsViewed,
    markAsUnread,
    markActivity,
    getLastViewedAt,
    getLastActivityAt,
  };
}
