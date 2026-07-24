import { TaskPendingView } from "@posthog/ui/features/task-detail/components/TaskPendingView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/tasks/pending/$key")({
  component: TaskPendingRoute,
});

function TaskPendingRoute() {
  const { key } = Route.useParams();
  return <TaskPendingView pendingTaskKey={key} />;
}
