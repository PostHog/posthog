import { NewTaskScreen } from "@posthog/ui/features/task-detail/components/NewTaskScreen";
import { createFileRoute } from "@tanstack/react-router";

// A new task filed to no space. Per-space new tasks live at /spaces/$id/new.
export const Route = createFileRoute("/_shell/new")({
  component: NewTaskScreen,
});
