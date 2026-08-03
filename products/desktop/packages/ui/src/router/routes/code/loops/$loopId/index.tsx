import { LoopDetailView } from "@posthog/ui/features/loops/components/LoopDetailView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/loops/$loopId/")({
  component: LoopDetailRoute,
});

function LoopDetailRoute() {
  const { loopId } = Route.useParams();
  return <LoopDetailView loopId={loopId} />;
}
