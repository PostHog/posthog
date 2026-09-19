import { WebsiteChannelHome } from "@posthog/ui/features/canvas/components/WebsiteChannelHome";
import { SpaceTabbedPage } from "@posthog/ui/features/canvas/components/work/SpaceTabbedPage";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import {
  SpaceActivitySkeleton,
  spaceRouteSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/")({
  component: ChannelHomeRoute,
  ...withRouteSkeleton(spaceRouteSkeleton(SpaceActivitySkeleton)),
});

function ChannelHomeRoute() {
  const { channelId } = Route.useParams();
  // Under the Work layout a space opens on Activity, its first tab.
  if (useWorkLayout()) {
    return (
      <SpaceTabbedPage channelId={channelId} tab="activity">
        <WebsiteChannelHome channelId={channelId} variant="work" />
      </SpaceTabbedPage>
    );
  }
  return <WebsiteChannelHome channelId={channelId} />;
}
