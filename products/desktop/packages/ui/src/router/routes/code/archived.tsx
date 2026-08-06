import { ArchivedTasksView } from "@posthog/ui/features/archive/ArchivedTasksView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/archived")({
  component: ArchivedTasksView,
});
