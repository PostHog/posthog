import { SketchpadView } from "@posthog/ui/features/sketchpad/components/SketchpadView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/sketchpads/$sketchpadId")({
  component: BoardRoute,
});

function BoardRoute() {
  const { sketchpadId } = Route.useParams();
  return <SketchpadView sketchpadId={sketchpadId} />;
}
