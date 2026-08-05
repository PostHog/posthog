import { TicketDetailView } from "@posthog/ui/features/support/components/TicketDetailView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/support/$ticketId")({
  component: TicketDetailRoute,
});

function TicketDetailRoute() {
  const { ticketId } = Route.useParams();
  return <TicketDetailView ticketId={ticketId} />;
}
