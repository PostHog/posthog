import { AgentUsersPane } from "@posthog/ui/features/agent-applications/components/AgentUsersPane";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/code/agents/applications/$idOrSlug/users",
)({
  component: AgentUsersRoute,
});

function AgentUsersRoute() {
  const { idOrSlug } = Route.useParams();
  return <AgentUsersPane idOrSlug={idOrSlug} />;
}
