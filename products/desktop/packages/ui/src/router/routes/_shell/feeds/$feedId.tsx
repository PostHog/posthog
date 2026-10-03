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
  // The picked task rides in the URL, as it does on Activity, so the location
  // says what the pane shows: a tab can name it, a reload keeps it, and a
  // report opened from a task artifact can return to it.
  validateSearch: (search: Record<string, unknown>): { task?: string } => ({
    task:
      typeof search.task === "string" && search.task ? search.task : undefined,
  }),
  ...withRouteSkeleton(ChannelSkeleton),
});

function TaskFeedRoute() {
  const { feedId } = Route.useParams();
  const { task: routeTaskId } = Route.useSearch();
  const channelsLayout = useChannelsLayout();
  return channelsLayout ? (
    <TaskFeedDetailPane feedId={feedId} routeTaskId={routeTaskId} />
  ) : (
    <TaskFeedHome feedId={feedId} />
  );
}
