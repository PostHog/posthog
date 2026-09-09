import { useHostTRPC } from "@posthog/host-router/react";
import type { SketchpadSummary } from "@posthog/shared";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_REFETCH_INTERVAL_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "@posthog/ui/features/canvas/hooks/spaceQueryPolicy";
import { useQuery } from "@tanstack/react-query";

interface SketchpadsResult {
  boards: SketchpadSummary[];
  isLoading: boolean;
  isError: boolean;
}

export function useSketchpads(
  channelId: string | undefined,
  enabled: boolean,
): SketchpadsResult {
  const trpc = useHostTRPC();
  const { data, isLoading, isError } = useQuery(
    trpc.sketchpad.list.queryOptions(
      { channelId },
      {
        enabled,
        meta: AUTH_SCOPED_QUERY_META,
        gcTime: SPACE_QUERY_GC_TIME_MS,
        refetchInterval: SPACE_QUERY_REFETCH_INTERVAL_MS,
        staleTime: SPACE_QUERY_STALE_TIME_MS,
      },
    ),
  );
  return { boards: data ?? [], isLoading, isError };
}
