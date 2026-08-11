import { AgentApplicationDetailView } from "@posthog/ui/features/agent-applications/components/AgentApplicationDetailView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/applications/$idOrSlug/")({
  component: AgentApplicationDetailRoute,
});

function AgentApplicationDetailRoute() {
  const { idOrSlug } = Route.useParams();
  return <AgentApplicationDetailView idOrSlug={idOrSlug} />;
}
