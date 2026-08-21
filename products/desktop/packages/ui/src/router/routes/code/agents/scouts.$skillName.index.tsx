import { ScoutDetailView } from "@posthog/ui/features/scouts/components/ScoutDetailView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/agents/scouts/$skillName/")({
  validateSearch: (search: Record<string, unknown>): { finding?: string } => ({
    finding: typeof search.finding === "string" ? search.finding : undefined,
  }),
  component: ScoutDetailRoute,
});

function ScoutDetailRoute() {
  const { skillName } = Route.useParams();
  const { finding } = Route.useSearch();
  return <ScoutDetailView skillSlug={skillName} highlightFindingId={finding} />;
}
