import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const DEFAULT_SETTINGS = {
  autoSuspendEnabled: true,
  maxActiveWorktrees: 5,
  autoSuspendAfterDays: 7,
};

export function useSuspensionSettings() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const settingsQueryKey = trpc.suspension.settings.queryKey();

  const { data: settings } = useQuery(trpc.suspension.settings.queryOptions());

  const updateMutation = useMutation(
    trpc.suspension.updateSettings.mutationOptions({
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: settingsQueryKey });
      },
    }),
  );

  const updateSettings = (
    update: Parameters<typeof updateMutation.mutateAsync>[0],
  ) => updateMutation.mutateAsync(update);

  return {
    settings: settings ?? DEFAULT_SETTINGS,
    updateSettings,
  };
}
