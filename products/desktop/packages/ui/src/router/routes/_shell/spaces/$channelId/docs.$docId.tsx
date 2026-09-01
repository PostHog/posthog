import { SpaceDocView } from "@posthog/ui/features/docs/components/SpaceDocView";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/docs/$docId")({
  component: SpaceDocRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function SpaceDocRoute() {
  const { channelId, docId } = Route.useParams();
  return <SpaceDocView channelId={channelId} docId={docId} />;
}
