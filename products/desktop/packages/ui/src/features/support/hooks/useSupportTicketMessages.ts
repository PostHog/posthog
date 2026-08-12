import type { SupportTicketMessagePage } from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { keepPreviousData } from "@tanstack/react-query";

/**
 * Fast enough that a customer's reply appears while the ticket is open. Reading
 * the thread has no side effects, unlike reading the ticket, so this is the poll
 * that carries liveness on an open ticket. It stops when the window loses focus
 * (no background refetch), which keeps an idle desk quiet.
 */
const THREAD_POLL_INTERVAL_MS = 5_000;

export function useSupportTicketMessages(
  ticketId: string | undefined,
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<SupportTicketMessagePage>(
    supportKeys.thread(ticketId ?? "none"),
    (client) => client.listSupportTicketMessages(ticketId as string),
    {
      enabled: !!ticketId && (options?.enabled ?? true),
      refetchInterval: THREAD_POLL_INTERVAL_MS,
      placeholderData: keepPreviousData,
    },
  );
}
