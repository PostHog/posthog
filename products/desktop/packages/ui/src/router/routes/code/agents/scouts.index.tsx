import { AgentsView } from "@posthog/ui/features/agents/components/AgentsView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/scouts/")({
  component: AgentsView,
});
