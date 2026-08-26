import type { SupportTicketView } from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

const VIEWS_STALE_TIME_MS = 5 * 60_000;

export function useSupportTicketViews(options?: { enabled?: boolean }) {
  return useAuthenticatedQuery<SupportTicketView[]>(
    supportKeys.views(),
    (client) => client.listSupportTicketViews(),
    {
      enabled: options?.enabled ?? true,
      staleTime: VIEWS_STALE_TIME_MS,
    },
  );
}
