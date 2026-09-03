import {
  isScoutDetailTab,
  type ScoutDetailTab,
} from "@posthog/core/scouts/scoutDetailTabs";
import { ScoutDetailView } from "@posthog/ui/features/scouts/components/ScoutDetailView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/agents/scouts/$skillName/")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { finding?: string; tab?: ScoutDetailTab } => ({
    finding: typeof search.finding === "string" ? search.finding : undefined,
    tab: isScoutDetailTab(search.tab) ? search.tab : undefined,
  }),
  component: ScoutDetailRoute,
});

function ScoutDetailRoute() {
  const { skillName } = Route.useParams();
  const { finding, tab } = Route.useSearch();
  return (
    <ScoutDetailView
      skillSlug={skillName}
      highlightFindingId={finding}
      tab={tab ?? (finding ? "signals" : "activity")}
    />
  );
}
