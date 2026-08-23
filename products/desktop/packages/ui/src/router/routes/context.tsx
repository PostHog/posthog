import { ContextWikiView } from "@posthog/ui/features/context-wiki/components/ContextWikiView";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/context")({
  component: ContextWikiView,
  ...withRouteSkeleton(AppPageSkeleton),
});
