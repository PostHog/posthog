import type {
  SupportTicketMessage,
  SupportTicketMessagePage,
} from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";

interface ReplyVariables {
  ticketId: string;
  message: string;
  isPrivate: boolean;
}

export function useReplyToSupportTicket() {
  const queryClient = useQueryClient();

  return useAuthenticatedMutation<SupportTicketMessage, Error, ReplyVariables>(
    (client, { ticketId, message, isPrivate }) =>
      client.replyToSupportTicket(ticketId, { message, isPrivate }),
    {
      onSuccess: (sent, { ticketId }) => {
        queryClient.setQueryData<SupportTicketMessagePage>(
          supportKeys.thread(ticketId),
          (page) =>
            page && !page.results.some((message) => message.id === sent.id)
              ? { results: [...page.results, sent], count: page.count + 1 }
              : page,
        );
        queryClient.invalidateQueries({ queryKey: supportKeys.ticketLists() });
      },
      onError: () => {
        toast.error("Couldn't send", {
          description: "Check the thread before sending it again.",
        });
      },
    },
  );
}
