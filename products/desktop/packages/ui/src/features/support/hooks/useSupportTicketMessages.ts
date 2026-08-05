import type { TicketMessage } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

export function useSupportTicketMessages(
  ticketId: string,
): UseQueryResult<TicketMessage[]> {
  return useAuthenticatedQuery(
    ["support-ticket-messages", ticketId],
    (client) => client.listTicketMessages(ticketId),
  );
}
