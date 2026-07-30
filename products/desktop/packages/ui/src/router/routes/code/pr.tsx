import { PullRequestView } from "@posthog/ui/features/pr-review/PullRequestView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/pr")({
  component: PullRequestRoute,
  validateSearch: (search: Record<string, unknown>): { prUrl: string } => ({
    prUrl: typeof search.prUrl === "string" ? search.prUrl : "",
  }),
});

function PullRequestRoute() {
  const { prUrl } = Route.useSearch();
  return <PullRequestView prUrl={prUrl} />;
}
