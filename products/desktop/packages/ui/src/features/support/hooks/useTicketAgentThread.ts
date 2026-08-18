import type { SupportTicket } from "@posthog/api-client/posthog-client";
import {
  readTicketTaskId,
  withTicketTaskId,
} from "@posthog/core/support/ticketTaskLink";
import { useUpdateSupportTicket } from "@posthog/ui/features/support/hooks/useUpdateSupportTicket";
import { useCallback } from "react";

export function useTicketAgentThread(ticket: SupportTicket | undefined) {
  const updateTicket = useUpdateSupportTicket();
  const taskId = ticket ? readTicketTaskId(ticket.tags) : null;

  const linkTask = useCallback(
    (newTaskId: string) => {
      if (!ticket) {
        return;
      }
      updateTicket.mutate({
        ticketId: ticket.id,
        updates: { tags: withTicketTaskId(ticket.tags, newTaskId) },
      });
    },
    [ticket, updateTicket],
  );

  return { taskId, linkTask };
}
