import { LoopDetailView } from "@posthog/ui/features/loops/components/LoopDetailView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/loops/$loopId/")({
  component: LoopDetailRoute,
  validateSearch: (search: Record<string, unknown>): { edit?: boolean } => ({
    edit: search.edit === true || search.edit === "true",
  }),
});

function LoopDetailRoute() {
  const { loopId } = Route.useParams();
  const { edit } = Route.useSearch();
  return <LoopDetailView loopId={loopId} startEditing={edit === true} />;
}
