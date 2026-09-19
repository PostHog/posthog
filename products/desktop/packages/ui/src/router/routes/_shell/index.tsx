import { HomeView } from "@posthog/ui/features/canvas/grid/HomeView";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import { NewTaskScreen } from "@posthog/ui/features/task-detail/components/NewTaskScreen";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/")({
  component: RootRoute,
});

function RootRoute() {
  // Home is the spaces layout's landing screen. Without that layout there is no
  // Home, and the app opens on a new task the way it always did. The Work
  // layout has no home either: a fresh tab is a new session.
  const channelsLayout = useChannelsLayout();
  const workLayout = useWorkLayout();
  return channelsLayout && !workLayout ? <HomeView /> : <NewTaskScreen />;
}
