import { AgentRunDetail } from "@posthog/ui/features/inbox/components/AgentRunDetail";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/runs/$reportId")({
  component: RunDetailRoute,
});

function RunDetailRoute() {
  const { reportId } = Route.useParams();
  return <AgentRunDetail reportId={reportId} />;
}
