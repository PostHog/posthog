import { WebsiteChannelHome } from "@posthog/ui/features/canvas/components/WebsiteChannelHome";
import { SpaceTabbedPage } from "@posthog/ui/features/canvas/components/work/SpaceTabbedPage";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import {
  SpaceActivitySkeleton,
  spaceRouteSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

// The space's feed and pull requests. Under the Work layout this is the
// Activity tab; without it the feed is the space's index and this route only
// mirrors it.
export const Route = createFileRoute("/_shell/spaces/$channelId/activity")({
  component: ChannelActivityRoute,
  ...withRouteSkeleton(spaceRouteSkeleton(SpaceActivitySkeleton)),
});

function ChannelActivityRoute() {
  const { channelId } = Route.useParams();
  if (useWorkLayout()) {
    return (
      <SpaceTabbedPage channelId={channelId} tab="activity">
        <WebsiteChannelHome channelId={channelId} variant="work" />
      </SpaceTabbedPage>
    );
  }
  return <WebsiteChannelHome channelId={channelId} />;
}
