import { SpaceDocView } from "@posthog/ui/features/docs/components/SpaceDocView";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/docs/$docId")({
  component: SpaceDocRoute,
  // `?thread=<anchor key>` opens that thread beside the page.
  validateSearch: (search: Record<string, unknown>): { thread?: string } =>
    typeof search.thread === "string" && search.thread
      ? { thread: search.thread }
      : {},
  ...withRouteSkeleton(ChannelSkeleton),
});

function SpaceDocRoute() {
  const { channelId, docId } = Route.useParams();
  const { thread } = Route.useSearch();
  return (
    <SpaceDocView channelId={channelId} docId={docId} openThreadKey={thread} />
  );
}
