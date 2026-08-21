import { WebsiteChannelLoops } from "@posthog/ui/features/canvas/components/WebsiteChannelLoops";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/loops")({
  component: ChannelLoopsRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function ChannelLoopsRoute() {
  const { channelId } = Route.useParams();
  return <WebsiteChannelLoops channelId={channelId} />;
}
