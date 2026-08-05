import type { Ticket, TicketUpdate } from "@posthog/api-client/posthog-client";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import type { UseMutationResult } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";

export function useUpdateSupportTicket(
  ticketId: string,
): UseMutationResult<Ticket, Error, TicketUpdate> {
  const queryClient = useQueryClient();
  return useAuthenticatedMutation(
    (client, updates: TicketUpdate) => client.updateTicket(ticketId, updates),
    {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: ["support-ticket", ticketId],
        });
        void queryClient.invalidateQueries({ queryKey: ["support-tickets"] });
      },
    },
  );
}
