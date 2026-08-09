import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

// The server caches this for 30s, so polling faster just burns requests.
const SUPPORT_UNREAD_REFETCH_INTERVAL_MS = 60_000;

/**
 * Unread customer messages across the team's non-resolved tickets — the nav
 * badge count. `enabled` is the flag gate: with Support off this must not poll.
 */
export function useSupportUnreadCount(
  enabled: boolean,
): UseQueryResult<number> {
  return useAuthenticatedQuery(
    ["support-unread-count"],
    (client) => client.getTicketUnreadCount(),
    {
      enabled,
      refetchInterval: SUPPORT_UNREAD_REFETCH_INTERVAL_MS,
    },
  );
}
