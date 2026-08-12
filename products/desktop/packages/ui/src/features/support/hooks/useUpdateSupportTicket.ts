import type {
  SupportTicket,
  SupportTicketUpdate,
} from "@posthog/api-client/posthog-client";
import { predictTicketUpdate } from "@posthog/core/support/ticketState";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import {
  cacheSupportTicket,
  getCachedSupportTicket,
} from "@posthog/ui/features/support/supportQueries";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";

interface UpdateTicketVariables {
  idOrNumber: string;
  updates: SupportTicketUpdate;
}

interface UpdateTicketContext {
  previous?: SupportTicket;
}

/**
 * Triage writes: status, priority, snooze, tags and assignment.
 *
 * The optimistic write runs the server's own snooze transitions through
 * `predictTicketUpdate`, so a snoozed ticket does not flick through its old
 * status on the way to the response. The response is authoritative and replaces
 * the prediction; the queue is refetched after settling because a status change
 * can move a ticket out of the current filter.
 */
export function useUpdateSupportTicket() {
  const queryClient = useQueryClient();

  return useAuthenticatedMutation<SupportTicket, Error, UpdateTicketVariables>(
    (client, { idOrNumber, updates }) =>
      client.updateSupportTicket(idOrNumber, updates),
    {
      onMutate: async ({ idOrNumber, updates }) => {
        const previous = getCachedSupportTicket(idOrNumber);
        if (previous) {
          cacheSupportTicket(
            queryClient,
            predictTicketUpdate(previous, updates),
          );
        }
        return { previous } satisfies UpdateTicketContext;
      },
      onSuccess: (ticket) => {
        cacheSupportTicket(queryClient, ticket);
      },
      onError: (error, _variables, context) => {
        const previous = (context as UpdateTicketContext | undefined)?.previous;
        if (previous) {
          cacheSupportTicket(queryClient, previous);
        }
        toast.error(error.message || "Could not update the ticket");
      },
      onSettled: () => {
        queryClient.invalidateQueries({ queryKey: supportKeys.ticketLists() });
        queryClient.invalidateQueries({ queryKey: supportKeys.unreadCount() });
      },
    },
  );
}
