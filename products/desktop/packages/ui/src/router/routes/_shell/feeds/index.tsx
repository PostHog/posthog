import { SavedSearchesIndex } from "@posthog/ui/features/canvas/components/SavedSearchesIndex";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/feeds/")({
  component: SavedSearchesIndexRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function SavedSearchesIndexRoute() {
  return <SavedSearchesIndex />;
}
