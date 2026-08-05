import type { TicketMessage } from "@posthog/api-client/posthog-client";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import type { UseMutationResult } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";

export interface TicketReplyInput {
  message: string;
  isPrivate: boolean;
}

export function useSupportTicketReply(
  ticketId: string,
): UseMutationResult<TicketMessage, Error, TicketReplyInput> {
  const queryClient = useQueryClient();
  return useAuthenticatedMutation(
    (client, { message, isPrivate }: TicketReplyInput) =>
      client.replyToTicket(ticketId, message, isPrivate),
    {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: ["support-ticket-messages", ticketId],
        });
        void queryClient.invalidateQueries({
          queryKey: ["support-ticket", ticketId],
        });
        void queryClient.invalidateQueries({ queryKey: ["support-tickets"] });
      },
    },
  );
}
