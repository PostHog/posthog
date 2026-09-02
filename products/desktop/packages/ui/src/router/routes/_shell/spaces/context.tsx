import { ContextWikiView } from "@posthog/ui/features/context-wiki/components/ContextWikiView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/context")({
  validateSearch: (search: Record<string, unknown>) => ({
    path: typeof search.path === "string" ? search.path : undefined,
  }),
  component: SpacesContextRoute,
});

function SpacesContextRoute() {
  const { path } = Route.useSearch();
  return <ContextWikiView initialPath={path} />;
}
