import { WebsiteContext } from "@posthog/ui/features/canvas/components/WebsiteContext";
import { SpaceTabbedPage } from "@posthog/ui/features/canvas/components/work/SpaceTabbedPage";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import {
  SpaceContextSkeleton,
  spaceRouteSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/context")({
  component: ContextRoute,
  ...withRouteSkeleton(spaceRouteSkeleton(SpaceContextSkeleton)),
});

function ContextRoute() {
  const { channelId } = Route.useParams();
  if (useWorkLayout()) {
    return (
      <SpaceTabbedPage channelId={channelId} tab="context">
        <WebsiteContext channelId={channelId} />
      </SpaceTabbedPage>
    );
  }
  return <WebsiteContext channelId={channelId} />;
}
