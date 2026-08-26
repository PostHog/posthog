import { ScoutFindingsView } from "@posthog/ui/features/scouts/components/ScoutFindingsView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/agents/scouts/findings")({
  component: ScoutFindingsView,
});
