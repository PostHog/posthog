import { WebsiteChannelArtifacts } from "@posthog/ui/features/canvas/components/WebsiteChannelArtifacts";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/artifacts")({
  component: ChannelArtifactsRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function ChannelArtifactsRoute() {
  const { channelId } = Route.useParams();
  return <WebsiteChannelArtifacts channelId={channelId} />;
}
