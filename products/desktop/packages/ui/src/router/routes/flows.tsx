import { AgentFlowsView } from "@posthog/ui/features/agent-flows/AgentFlowsView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/flows")({
  component: AgentFlowsView,
});
