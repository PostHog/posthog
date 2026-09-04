import type { TaskArtifactSharing } from "@posthog/api-client/posthog-client";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const SHARING_STALE_TIME_MS = 30_000;

export function artifactSharingKey(
  taskId: string,
  artifactId: string,
): string[] {
  return ["task-artifact-sharing", taskId, artifactId];
}

/** One upload's public-sharing state. `data` is null when the backend cannot share artifacts. */
export function useArtifactSharingQuery(
  taskId: string,
  artifactId: string,
): {
  data: TaskArtifactSharing | null | undefined;
  isLoading: boolean;
  isError: boolean;
} {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const { data, isLoading, isError } = useQuery({
    queryKey: artifactSharingKey(taskId, artifactId),
    queryFn: () => sessionService.getTaskArtifactSharing(taskId, artifactId),
    meta: AUTH_SCOPED_QUERY_META,
    staleTime: SHARING_STALE_TIME_MS,
  });
  return { data, isLoading, isError };
}

export function useSetArtifactSharing(
  taskId: string,
  artifactId: string,
): {
  setEnabled: (enabled: boolean) => Promise<TaskArtifactSharing | null>;
  isPending: boolean;
} {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (enabled: boolean) =>
      sessionService.setTaskArtifactSharing(taskId, artifactId, enabled),
    onSuccess: (sharing) => {
      queryClient.setQueryData(artifactSharingKey(taskId, artifactId), sharing);
    },
    onError: (error) => {
      toast.error("Couldn't update public sharing", {
        description: error instanceof Error ? error.message : String(error),
      });
    },
  });
  return {
    setEnabled: (enabled) => mutation.mutateAsync(enabled).catch(() => null),
    isPending: mutation.isPending,
  };
}
