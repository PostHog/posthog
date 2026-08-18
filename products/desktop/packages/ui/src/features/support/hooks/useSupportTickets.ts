import type {
  SupportTicket,
  SupportTicketListOptions,
  SupportTicketPage,
} from "@posthog/api-client/posthog-client";
import { SUPPORT_TICKETS_PAGE_SIZE } from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedInfiniteQuery } from "@posthog/ui/hooks/useAuthenticatedInfiniteQuery";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { keepPreviousData } from "@tanstack/react-query";
import { useMemo } from "react";

const TICKET_LIST_POLL_INTERVAL_MS = 30_000;

export function useSupportTickets(
  options: SupportTicketListOptions,
  queryOptions?: { enabled?: boolean; refetchInterval?: number | false },
) {
  return useAuthenticatedQuery<SupportTicketPage>(
    supportKeys.ticketList(options),
    (client) => client.listSupportTickets(options),
    {
      enabled: queryOptions?.enabled ?? true,
      refetchInterval:
        queryOptions?.refetchInterval ?? TICKET_LIST_POLL_INTERVAL_MS,
      placeholderData: keepPreviousData,
    },
  );
}

export function nextSupportTicketOffset(
  lastPage: SupportTicketPage,
  allPages: SupportTicketPage[],
): number | undefined {
  if (lastPage.results.length === 0) {
    return undefined;
  }
  const loaded = allPages.reduce(
    (total, page) => total + page.results.length,
    0,
  );
  return loaded < lastPage.count ? loaded : undefined;
}

export function flattenSupportTicketPages(
  pages: SupportTicketPage[],
): SupportTicket[] {
  const seen = new Set<string>();
  const tickets: SupportTicket[] = [];
  for (const page of pages) {
    for (const ticket of page.results) {
      if (!seen.has(ticket.id)) {
        seen.add(ticket.id);
        tickets.push(ticket);
      }
    }
  }
  return tickets;
}

export function useSupportTicketsInfinite(options: SupportTicketListOptions) {
  const query = useAuthenticatedInfiniteQuery<SupportTicketPage, number>(
    supportKeys.ticketListInfinite(options),
    (client, offset) =>
      client.listSupportTickets({
        ...options,
        limit: SUPPORT_TICKETS_PAGE_SIZE,
        offset,
      }),
    {
      initialPageParam: 0,
      getNextPageParam: nextSupportTicketOffset,
      refetchInterval: TICKET_LIST_POLL_INTERVAL_MS,
      placeholderData: keepPreviousData,
    },
  );

  const tickets = useMemo(
    () => flattenSupportTicketPages(query.data?.pages ?? []),
    [query.data?.pages],
  );

  return { ...query, tickets, totalCount: query.data?.pages[0]?.count ?? 0 };
}
