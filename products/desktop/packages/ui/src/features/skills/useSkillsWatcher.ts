import { useHostTRPC } from "@posthog/host-router/react";
import { useQueryClient } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";

/**
 * Invalidates every skills query when the writable skill roots change on
 * disk, so external edits (terminals, agent sessions) appear live.
 */
export function useSkillsWatcher() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  useSubscription(
    trpc.skills.watch.subscriptionOptions(undefined, {
      onData: () => {
        void queryClient.invalidateQueries(trpc.skills.pathFilter());
      },
    }),
  );
}
