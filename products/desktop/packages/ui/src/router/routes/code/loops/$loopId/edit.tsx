import { EditLoopView } from "@posthog/ui/features/loops/components/EditLoopView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/loops/$loopId/edit")({
  component: EditLoopRoute,
});

function EditLoopRoute() {
  const { loopId } = Route.useParams();
  return <EditLoopView loopId={loopId} />;
}
