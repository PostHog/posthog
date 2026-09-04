import { CanvasV2Gate } from "@posthog/ui/features/canvas-v2/components/CanvasV2Gate";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/canvases-v2")({
  component: CanvasesV2Layout,
  ...withRouteSkeleton(AppPageSkeleton),
});

function CanvasesV2Layout() {
  return (
    <CanvasV2Gate>
      <Outlet />
    </CanvasV2Gate>
  );
}
