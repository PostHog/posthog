import { WebsiteNewTask } from "@posthog/ui/features/canvas/components/WebsiteNewTask";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/website/$channelId/new")({
  component: NewTaskRoute,
});

function NewTaskRoute() {
  const { channelId } = Route.useParams();
  return <WebsiteNewTask channelId={channelId} />;
}
