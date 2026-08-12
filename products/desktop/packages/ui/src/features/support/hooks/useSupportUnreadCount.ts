import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

const UNREAD_COUNT_POLL_INTERVAL_MS = 30_000;

export function useSupportUnreadCount(options?: { enabled?: boolean }) {
  return useAuthenticatedQuery<number>(
    supportKeys.unreadCount(),
    (client) => client.getSupportTicketUnreadCount(),
    {
      enabled: options?.enabled ?? true,
      refetchInterval: UNREAD_COUNT_POLL_INTERVAL_MS,
      refetchIntervalInBackground: true,
    },
  );
}
