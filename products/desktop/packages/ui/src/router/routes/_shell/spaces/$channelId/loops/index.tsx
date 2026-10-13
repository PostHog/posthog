import { WebsiteChannelLoops } from "@posthog/ui/features/canvas/components/WebsiteChannelLoops";
import { SpaceTabbedPage } from "@posthog/ui/features/canvas/components/work/SpaceTabbedPage";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import {
  SpaceContextSkeleton,
  spaceRouteSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/loops/")({
  component: ChannelLoopsRoute,
  ...withRouteSkeleton(spaceRouteSkeleton(SpaceContextSkeleton)),
});

function ChannelLoopsRoute() {
  const { channelId } = Route.useParams();
  if (useWorkLayout()) {
    return (
      <SpaceTabbedPage channelId={channelId} tab="loops">
        <WebsiteChannelLoops channelId={channelId} />
      </SpaceTabbedPage>
    );
  }
  return <WebsiteChannelLoops channelId={channelId} />;
}
