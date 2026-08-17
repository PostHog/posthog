import { ZoomCanvas } from "@posthog/ui/features/zoom-canvas/components/ZoomCanvas";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/zoom")({
  component: ZoomCanvasRoute,
});

function ZoomCanvasRoute() {
  return <ZoomCanvas />;
}
