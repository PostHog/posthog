import type {
  SupportTicketListOptions,
  SupportTicketPage,
} from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { keepPreviousData } from "@tanstack/react-query";

/**
 * The queue is the surface's ambient poll. It reports `unread_team_count`
 * without clearing it, which the ticket endpoint does not, so freshness comes
 * from here rather than from reading each ticket.
 */
const TICKET_LIST_POLL_INTERVAL_MS = 30_000;

export function useSupportTickets(
  options: SupportTicketListOptions,
  queryOptions?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<SupportTicketPage>(
    supportKeys.ticketList(options),
    (client) => client.listSupportTickets(options),
    {
      enabled: queryOptions?.enabled ?? true,
      refetchInterval: TICKET_LIST_POLL_INTERVAL_MS,
      placeholderData: keepPreviousData,
    },
  );
}
