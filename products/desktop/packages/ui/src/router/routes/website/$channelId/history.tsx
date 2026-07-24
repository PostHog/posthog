import { WebsiteChannelHistory } from "@posthog/ui/features/canvas/components/WebsiteChannelHistory";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/history")({
  component: ChannelHistoryRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function ChannelHistoryRoute() {
  const { channelId } = Route.useParams();
  return <WebsiteChannelHistory channelId={channelId} />;
}
