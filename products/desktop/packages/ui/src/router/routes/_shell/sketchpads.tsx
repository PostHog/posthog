import { SketchpadGate } from "@posthog/ui/features/sketchpad/components/SketchpadGate";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/sketchpads")({
  component: SketchpadsLayout,
  ...withRouteSkeleton(AppPageSkeleton),
});

function SketchpadsLayout() {
  return (
    <SketchpadGate>
      <Outlet />
    </SketchpadGate>
  );
}
