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
  const channelsLayout = useChannelsLayout();
  const workLayout = useWorkLayout();
  return channelsLayout && !workLayout ? <HomeView /> : <NewTaskScreen />;
}
