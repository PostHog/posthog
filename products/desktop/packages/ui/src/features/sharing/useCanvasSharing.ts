import type { CanvasSharing } from "@posthog/core/canvas/dashboardSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const SHARING_STALE_TIME_MS = 30_000;

/** A canvas's public-sharing state. `data` is null when the backend cannot share canvases. */
export function useCanvasSharingQuery(dashboardId: string): {
  data: CanvasSharing | null | undefined;
  isLoading: boolean;
  isError: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading, isError } = useQuery(
    trpc.dashboards.sharing.queryOptions(
      { id: dashboardId },
      { meta: AUTH_SCOPED_QUERY_META, staleTime: SHARING_STALE_TIME_MS },
    ),
  );
  return { data, isLoading, isError };
}

export function useSetCanvasSharing(dashboardId: string): {
  setEnabled: (enabled: boolean) => Promise<CanvasSharing | null>;
  /** Point the public link at the latest published build. */
  updateLink: () => Promise<CanvasSharing | null>;
  setAllowForking: (allowForking: boolean) => Promise<CanvasSharing | null>;
  isPending: boolean;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const mutation = useMutation(
    trpc.dashboards.setSharing.mutationOptions({
      onSuccess: (sharing) => {
        queryClient.setQueryData(
          trpc.dashboards.sharing.queryKey({ id: dashboardId }),
          sharing,
        );
        // Enabling moves the pinned build, which the canvas record carries.
        void queryClient.invalidateQueries(trpc.dashboards.get.pathFilter());
      },
      onError: (error) => {
        toast.error("Couldn't update public sharing", {
          description: error instanceof Error ? error.message : String(error),
        });
      },
    }),
  );
  return {
    setEnabled: (enabled) =>
      mutation.mutateAsync({ id: dashboardId, enabled }).catch(() => null),
    updateLink: () =>
      mutation
        .mutateAsync({ id: dashboardId, enabled: true })
        .catch(() => null),
    setAllowForking: (allowForking) =>
      mutation.mutateAsync({ id: dashboardId, allowForking }).catch(() => null),
    isPending: mutation.isPending,
  };
}
