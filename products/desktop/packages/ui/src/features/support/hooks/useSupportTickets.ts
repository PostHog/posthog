import type {
  SupportTicketListOptions,
  SupportTicketPage,
} from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { keepPreviousData } from "@tanstack/react-query";

const TICKET_LIST_POLL_INTERVAL_MS = 30_000;

export function useSupportTickets(
  options: SupportTicketListOptions,
  queryOptions?: { enabled?: boolean; refetchInterval?: number | false },
) {
  return useAuthenticatedQuery<SupportTicketPage>(
    supportKeys.ticketList(options),
    (client) => client.listSupportTickets(options),
    {
      enabled: queryOptions?.enabled ?? true,
      refetchInterval:
        queryOptions?.refetchInterval ?? TICKET_LIST_POLL_INTERVAL_MS,
      placeholderData: keepPreviousData,
    },
  );
}
