import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/canvases-v2")({
  component: CanvasesV2Layout,
  ...withRouteSkeleton(AppPageSkeleton),
});

function CanvasesV2Layout() {
  return <Outlet />;
}
