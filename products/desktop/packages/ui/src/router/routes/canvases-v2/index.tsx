import { CanvasesV2ListView } from "@posthog/ui/features/canvas-v2/components/CanvasesV2ListView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/canvases-v2/")({
  component: CanvasesV2ListView,
});
