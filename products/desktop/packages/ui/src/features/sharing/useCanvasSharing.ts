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
      {
        meta: AUTH_SCOPED_QUERY_META,
        staleTime: SHARING_STALE_TIME_MS,
        // Another client can turn sharing off while the dialog is closed, so
        // each opening asks the server rather than serving the cached toggle.
        refetchOnMount: "always",
      },
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
  const onSuccess = (sharing: CanvasSharing): void => {
    queryClient.setQueryData(
      trpc.dashboards.sharing.queryKey({ id: dashboardId }),
      sharing,
    );
    // Enabling, disabling, and publishing can move the pinned build carried by the canvas
    // record and list rows, so refresh both surfaces together.
    void queryClient.invalidateQueries(trpc.dashboards.get.pathFilter());
    void queryClient.invalidateQueries(trpc.dashboards.list.pathFilter());
  };
  const onError = (error: unknown): void => {
    toast.error("Couldn't update public sharing", {
      description: error instanceof Error ? error.message : String(error),
    });
  };
  const mutation = useMutation(
    trpc.dashboards.setSharing.mutationOptions({ onSuccess, onError }),
  );
  const publishMutation = useMutation(
    trpc.dashboards.publishSharing.mutationOptions({ onSuccess, onError }),
  );
  return {
    setEnabled: (enabled) =>
      mutation.mutateAsync({ id: dashboardId, enabled }).catch(() => null),
    updateLink: () =>
      publishMutation.mutateAsync({ id: dashboardId }).catch(() => null),
    setAllowForking: (allowForking) =>
      mutation.mutateAsync({ id: dashboardId, allowForking }).catch(() => null),
    isPending: mutation.isPending || publishMutation.isPending,
  };
}
