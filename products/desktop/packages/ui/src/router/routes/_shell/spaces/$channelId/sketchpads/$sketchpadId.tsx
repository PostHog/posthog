import { SketchpadGate } from "@posthog/ui/features/sketchpad/components/SketchpadGate";
import { SketchpadView } from "@posthog/ui/features/sketchpad/components/SketchpadView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_shell/spaces/$channelId/sketchpads/$sketchpadId",
)({
  component: SpaceBoardRoute,
});

function SpaceBoardRoute() {
  const { channelId, sketchpadId } = Route.useParams();
  return (
    <SketchpadGate>
      <SketchpadView sketchpadId={sketchpadId} channelId={channelId} />
    </SketchpadGate>
  );
}
