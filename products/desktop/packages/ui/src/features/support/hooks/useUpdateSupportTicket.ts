import type {
  SupportTicket,
  SupportTicketUpdate,
} from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";

interface UpdateTicketVariables {
  ticketId: string;
  updates: SupportTicketUpdate;
}

export function useUpdateSupportTicket() {
  const queryClient = useQueryClient();

  return useAuthenticatedMutation<SupportTicket, Error, UpdateTicketVariables>(
    (client, { ticketId, updates }) =>
      client.updateSupportTicket(ticketId, updates),
    {
      onSuccess: (ticket) => {
        queryClient.setQueryData(supportKeys.ticketDetail(ticket.id), ticket);
        queryClient.invalidateQueries({ queryKey: supportKeys.ticketLists() });
        queryClient.invalidateQueries({
          queryKey: supportKeys.activity(ticket.id),
        });
      },
      onError: (error) => {
        toast.error(error.message || "Could not update the ticket");
      },
    },
  );
}
