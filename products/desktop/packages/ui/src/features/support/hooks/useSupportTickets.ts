import type {
  ListTicketsOptions,
  PaginatedTicketList,
} from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

const SUPPORT_TICKETS_REFETCH_INTERVAL_MS = 30_000;

export function useSupportTickets(
  options?: ListTicketsOptions,
): UseQueryResult<PaginatedTicketList> {
  return useAuthenticatedQuery(
    ["support-tickets", options ?? {}],
    (client) => client.listTickets(options),
    { refetchInterval: SUPPORT_TICKETS_REFETCH_INTERVAL_MS },
  );
}
