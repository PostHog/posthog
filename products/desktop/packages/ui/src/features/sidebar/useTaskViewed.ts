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

  const markActivityMutationRef = useRef(markActivityMutation);
  markActivityMutationRef.current = markActivityMutation;

  const markAsViewed = useCallback((taskId: string) => {
    markViewedMutationRef.current.mutate({ taskId });
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
    markActivity,
    getLastViewedAt,
    getLastActivityAt,
  };
}
