import { WebsiteChannelHome } from "@posthog/ui/features/canvas/components/WebsiteChannelHome";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/")({
  component: ChannelHomeRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function ChannelHomeRoute() {
  const { channelId } = Route.useParams();
  return <WebsiteChannelHome channelId={channelId} />;
}
