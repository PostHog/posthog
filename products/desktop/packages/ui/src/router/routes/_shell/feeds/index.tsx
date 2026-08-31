import {
  useProjectTaskFeeds,
  useProjectTaskFeedsReady,
} from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute, Navigate } from "@tanstack/react-router";

// A saved search is switched from the header of the search you are on, so
// `/feeds` lists nothing of its own — it opens the first one instead. It stays
// a route because the rail, saved locations and legacy links land on it.
export const Route = createFileRoute("/_shell/feeds/")({
  component: SavedSearchesIndexRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function SavedSearchesIndexRoute() {
  const feeds = useProjectTaskFeeds();
  const ready = useProjectTaskFeedsReady();
  const firstFeedId = feeds[0]?.id;
  // The searches are read back from disk, so an empty list before that is not
  // an answer — redirecting on it would drop the user on Spaces.
  if (!ready) return <ChannelSkeleton />;
  if (firstFeedId) {
    return (
      <Navigate replace to="/feeds/$feedId" params={{ feedId: firstFeedId }} />
    );
  }
  return <Navigate replace to="/spaces" />;
}
