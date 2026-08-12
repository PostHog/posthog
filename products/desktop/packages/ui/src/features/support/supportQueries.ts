import { requestErrorStatus } from "@posthog/api-client/fetcher";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { resolveService } from "@posthog/di/container";
import { NotAuthenticatedError } from "@posthog/shared";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import { queryOptions } from "@tanstack/react-query";

/**
 * How long an opened ticket stays fresh. Reading one marks it read for the whole
 * team server-side, so this query never polls and never refetches in the
 * background: writes seed the cache from their own authoritative response, and
 * the thread poll supplies liveness while the ticket is open.
 */
const TICKET_DETAIL_STALE_TIME_MS = 30_000;

/**
 * Shared definition so a route loader and the component read one cache entry.
 * The id may be a UUID or a ticket number; both resolve server-side.
 */
export function supportTicketQuery(idOrNumber: string) {
  return queryOptions({
    queryKey: supportKeys.ticketDetail(idOrNumber),
    queryFn: async (): Promise<SupportTicket> => {
      const client = await getAuthenticatedClient();
      if (!client) {
        throw new NotAuthenticatedError();
      }
      return await client.getSupportTicket(idOrNumber);
    },
    meta: AUTH_SCOPED_QUERY_META,
    staleTime: TICKET_DETAIL_STALE_TIME_MS,
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: (failureCount, error) =>
      !isTicketNotFoundError(error) && failureCount < 3,
  });
}

export function isTicketNotFoundError(error: unknown): boolean {
  return requestErrorStatus(error) === 404;
}

/** Read a ticket already in cache, for a route loader that must not block. */
export function getCachedSupportTicket(
  idOrNumber: string,
): SupportTicket | undefined {
  return resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  ).getQueryData<SupportTicket>(supportKeys.ticketDetail(idOrNumber));
}

/**
 * Seed both cache entries a ticket can be keyed under. A ticket opened by
 * number and the same ticket written by UUID would otherwise leave one of the
 * two entries stale behind the other.
 */
export function cacheSupportTicket(
  client: ImperativeQueryClient,
  ticket: SupportTicket,
): void {
  client.setQueryData(supportKeys.ticketDetail(ticket.id), ticket);
  client.setQueryData(
    supportKeys.ticketDetail(String(ticket.ticket_number)),
    ticket,
  );
}
