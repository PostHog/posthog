import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { TicketDetailView } from "@posthog/ui/features/support/components/TicketDetailView";
import { getCachedSupportTicket } from "@posthog/ui/features/support/supportQueries";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/support/$ticketId")({
  component: TicketDetailRoute,
  pendingComponent: () => null,
  loader: ({ params }): SupportTicket | null =>
    getCachedSupportTicket(params.ticketId) ?? null,
});

function TicketDetailRoute() {
  const { ticketId } = Route.useParams();
  const cachedTicket = Route.useLoaderData();

  return <TicketDetailView ticketId={ticketId} cachedTicket={cachedTicket} />;
}
