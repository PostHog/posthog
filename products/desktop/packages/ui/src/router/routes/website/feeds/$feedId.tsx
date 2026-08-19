import { TaskFeedHome } from "@posthog/ui/features/canvas/components/TaskFeedHome";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/feeds/$feedId")({
  component: TaskFeedRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function TaskFeedRoute() {
  const { feedId } = Route.useParams();
  return <TaskFeedHome feedId={feedId} />;
}
