import { TaskFeedDetailPane } from "@posthog/ui/features/canvas/components/TaskFeedDetailPane";
import { TaskFeedHome } from "@posthog/ui/features/canvas/components/TaskFeedHome";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/feeds/$feedId")({
  component: TaskFeedRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function TaskFeedRoute() {
  const { feedId } = Route.useParams();
  const channelsLayout = useChannelsLayout();
  return channelsLayout ? (
    <TaskFeedDetailPane feedId={feedId} />
  ) : (
    <TaskFeedHome feedId={feedId} />
  );
}
