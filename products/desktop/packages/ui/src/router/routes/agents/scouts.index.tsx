import { AgentsView } from "@posthog/ui/features/agents/components/AgentsView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/agents/scouts/")({
  component: AgentsView,
});
