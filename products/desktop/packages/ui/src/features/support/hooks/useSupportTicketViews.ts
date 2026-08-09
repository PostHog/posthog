import type { TicketView } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

// Views are team-shared config edited elsewhere (PostHog, hogdesk), so they
// change on a human timescale — no need to refetch them per queue poll.
const SUPPORT_TICKET_VIEWS_STALE_MS = 60_000;

/**
 * Saved ticket views the team has defined elsewhere. Read-only here: the queue
 * applies one by `short_id` and lets the server expand it, so we never have to
 * interpret the `filters` blob (which carries criteria our filter set can't
 * express — tag match modes, exclusions, date ranges).
 */
export function useSupportTicketViews(): UseQueryResult<TicketView[]> {
  return useAuthenticatedQuery(
    ["support-ticket-views"],
    (client) => client.listTicketViews(),
    { staleTime: SUPPORT_TICKET_VIEWS_STALE_MS },
  );
}
