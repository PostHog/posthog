import type {
  SupportTicketMessage,
  SupportTicketMessagePage,
} from "@posthog/api-client/posthog-client";
import {
  classifyReplyFailure,
  findSentReply,
} from "@posthog/core/support/replyOutcome";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";

interface ReplyVariables {
  ticketId: string;
  message: string;
  isPrivate: boolean;
}

/**
 * Post a customer-facing reply or an internal note.
 *
 * There is no optimistic row: a reply that reaches a customer must never appear
 * in the thread before the server confirms it. When a send fails in a way that
 * leaves the outcome unknown (dropped connection, timeout, a concurrent
 * identical send, a server error), the thread is re-read and searched for the
 * message before the person is told anything, because resending a reply that
 * did land sends it to the customer twice. A rejection that definitely wrote
 * nothing, throttling included, surfaces as a plain error with the draft intact.
 */
export function useReplyToSupportTicket() {
  const queryClient = useQueryClient();

  return useAuthenticatedMutation<SupportTicketMessage, Error, ReplyVariables>(
    async (client, { ticketId, message, isPrivate }) => {
      const startedAt = Date.now();

      try {
        const { message: sent } = await client.replyToSupportTicket(ticketId, {
          message,
          isPrivate,
        });
        return sent;
      } catch (error) {
        if (classifyReplyFailure(error) === null) {
          throw error;
        }

        const thread = await client.listSupportTicketMessages(ticketId);
        const recovered = findSentReply(thread.results, {
          message,
          isPrivate,
          startedAt,
        });

        if (recovered) {
          return recovered;
        }

        throw new Error(
          "We could not confirm your message was added. Check the thread before sending it again.",
        );
      }
    },
    {
      onSuccess: (sent, { ticketId }) => {
        queryClient.setQueryData<SupportTicketMessagePage>(
          supportKeys.thread(ticketId),
          (page) => {
            if (!page) {
              return page;
            }
            if (page.results.some((message) => message.id === sent.id)) {
              return page;
            }
            return {
              results: [...page.results, sent],
              count: page.count + 1,
            };
          },
        );
        queryClient.invalidateQueries({ queryKey: supportKeys.ticketLists() });
      },
      onError: (error) => {
        toast.error(error.message || "Could not send the message");
      },
    },
  );
}
