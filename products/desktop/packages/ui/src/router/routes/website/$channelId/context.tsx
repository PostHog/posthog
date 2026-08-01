import { WebsiteContext } from "@posthog/ui/features/canvas/components/WebsiteContext";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/context")({
  component: ContextRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function ContextRoute() {
  const { channelId } = Route.useParams();
  return <WebsiteContext channelId={channelId} />;
}
