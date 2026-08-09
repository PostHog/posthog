import type { TicketView } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

// Views are team-shared config edited elsewhere (PostHog, hogdesk), so they
// change on a human timescale — no need to refetch them per queue poll.
const SUPPORT_TICKET_VIEWS_STALE_MS = 60_000;

/** Shared so the favorite mutation writes the cache this query reads. */
export const SUPPORT_TICKET_VIEWS_QUERY_KEY = ["support-ticket-views"];

/**
 * Saved ticket views the team has defined elsewhere. Views are created,
 * renamed and deleted in PostHog; the only write this surface makes is
 * favoriting. The queue applies a view by `short_id` and lets the server
 * expand it, so we never interpret the `filters` blob (which carries criteria
 * our filter set can't express — tag match modes, exclusions, date ranges).
 */
export function useSupportTicketViews(): UseQueryResult<TicketView[]> {
  return useAuthenticatedQuery(
    SUPPORT_TICKET_VIEWS_QUERY_KEY,
    (client) => client.listTicketViews(),
    { staleTime: SUPPORT_TICKET_VIEWS_STALE_MS },
  );
}
