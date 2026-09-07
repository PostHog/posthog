import { CanvasesRoute } from "@posthog/ui/features/canvas/components/CanvasesRoute";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/canvases")({
  validateSearch: (search: Record<string, unknown>) => ({
    canvas:
      typeof search.canvas === "string" && search.canvas
        ? search.canvas
        : undefined,
  }),
  component: CanvasesRoute,
});
