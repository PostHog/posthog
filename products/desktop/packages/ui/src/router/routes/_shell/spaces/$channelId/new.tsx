import { SpaceNewTask } from "@posthog/ui/features/canvas/components/SpaceNewTask";
import { validateNewTaskSearch } from "@posthog/ui/router/newTaskSearch";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/new")({
  validateSearch: validateNewTaskSearch,
  component: NewTaskRoute,
});

function NewTaskRoute() {
  const { channelId } = Route.useParams();
  const { mode } = Route.useSearch();
  return (
    <SpaceNewTask
      channelId={channelId}
      initialAutoresearch={mode === "autoresearch"}
    />
  );
}
