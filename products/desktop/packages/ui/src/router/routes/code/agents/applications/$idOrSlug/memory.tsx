import { AgentMemoryPane } from "@posthog/ui/features/agent-applications/components/AgentMemoryPane";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/code/agents/applications/$idOrSlug/memory",
)({
  component: AgentMemoryRoute,
});

function AgentMemoryRoute() {
  const { idOrSlug } = Route.useParams();
  return <AgentMemoryPane idOrSlug={idOrSlug} />;
}
