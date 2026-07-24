import { AgentSessionTranscriptView } from "@posthog/ui/features/agent-applications/components/AgentSessionTranscriptView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/code/agents/applications/$idOrSlug/sessions/$sessionId",
)({
  component: AgentSessionRoute,
});

function AgentSessionRoute() {
  const { idOrSlug, sessionId } = Route.useParams();
  return (
    <AgentSessionTranscriptView idOrSlug={idOrSlug} sessionId={sessionId} />
  );
}
