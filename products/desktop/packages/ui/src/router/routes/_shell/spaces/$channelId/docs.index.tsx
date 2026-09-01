import { SpaceDocsHome } from "@posthog/ui/features/docs/components/SpaceDocsHome";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/docs/")({
  component: SpaceDocsIndexRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function SpaceDocsIndexRoute() {
  const { channelId } = Route.useParams();
  return <SpaceDocsHome channelId={channelId} />;
}
