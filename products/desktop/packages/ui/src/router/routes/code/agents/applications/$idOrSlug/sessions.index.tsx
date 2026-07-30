import { AgentSessionsPane } from "@posthog/ui/features/agent-applications/components/AgentSessionsPane";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/code/agents/applications/$idOrSlug/sessions/",
)({
  component: AgentSessionsRoute,
});

function AgentSessionsRoute() {
  const { idOrSlug } = Route.useParams();
  return <AgentSessionsPane idOrSlug={idOrSlug} />;
}
