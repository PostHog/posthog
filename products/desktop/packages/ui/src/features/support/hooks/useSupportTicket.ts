import type { Ticket } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

export function useSupportTicket(ticketId: string): UseQueryResult<Ticket> {
  return useAuthenticatedQuery(["support-ticket", ticketId], (client) =>
    client.getTicket(ticketId),
  );
}
