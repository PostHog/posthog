import { SpacesIndex } from "@posthog/ui/features/canvas/components/SpacesIndex";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/spaces/")({
  component: SpacesIndex,
});
