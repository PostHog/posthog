import { SpaceNewTask } from "@posthog/ui/features/canvas/components/SpaceNewTask";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/$channelId/new")({
  component: NewTaskRoute,
  validateSearch: (search: Record<string, unknown>): { guided?: boolean } => ({
    // Pinned URL parameter: first-run links and saved startup locations depend on it.
    guided: search.guided === true || search.guided === "true" || undefined,
  }),
});

function NewTaskRoute() {
  const { channelId } = Route.useParams();
  const { guided } = Route.useSearch();
  return <SpaceNewTask channelId={channelId} guidedFirstTask={guided} />;
}
