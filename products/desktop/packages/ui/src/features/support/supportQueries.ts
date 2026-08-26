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

const TICKET_DETAIL_STALE_TIME_MS = 30_000;

export function supportTicketQuery(ticketId: string) {
  return queryOptions({
    queryKey: supportKeys.ticketDetail(ticketId),
    queryFn: async (): Promise<SupportTicket> => {
      const client = await getAuthenticatedClient();
      if (!client) {
        throw new NotAuthenticatedError();
      }
      return await client.getSupportTicket(ticketId);
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

export function getCachedSupportTicket(
  ticketId: string,
): SupportTicket | undefined {
  return resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  ).getQueryData<SupportTicket>(supportKeys.ticketDetail(ticketId));
}
