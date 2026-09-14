import { NewTaskScreen } from "@posthog/ui/features/task-detail/components/NewTaskScreen";
import { validateNewTaskSearch } from "@posthog/ui/router/newTaskSearch";
import { createFileRoute } from "@tanstack/react-router";

// A new task filed to no space. Per-space new tasks live at /spaces/$id/new.
export const Route = createFileRoute("/_shell/new")({
  validateSearch: validateNewTaskSearch,
  component: NewTaskRoute,
});

function NewTaskRoute() {
  const { mode } = Route.useSearch();
  return <NewTaskScreen initialAutoresearch={mode === "autoresearch"} />;
}
