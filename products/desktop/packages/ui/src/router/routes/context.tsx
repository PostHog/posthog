import { ContextWikiView } from "@posthog/ui/features/context-wiki/components/ContextWikiView";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/context")({
  validateSearch: (search: Record<string, unknown>) => ({
    path: typeof search.path === "string" ? search.path : undefined,
  }),
  component: ContextRoute,
  ...withRouteSkeleton(AppPageSkeleton),
});

function ContextRoute() {
  const { path } = Route.useSearch();
  return <ContextWikiView initialPath={path} />;
}
