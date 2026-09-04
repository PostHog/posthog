import { useCanvasesV2Flag } from "@posthog/ui/features/feature-flags/useCanvasesV2Flag";
import { useFeatureFlagsLoaded } from "@posthog/ui/features/feature-flags/useFeatureFlagsLoaded";
import {
  AppPageSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute, Navigate, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/canvases-v2")({
  component: CanvasesV2Layout,
  ...withRouteSkeleton(AppPageSkeleton),
});

function CanvasesV2Layout() {
  const enabled = useCanvasesV2Flag();
  const flagsLoaded = useFeatureFlagsLoaded();

  if (enabled) return <Outlet />;
  if (!flagsLoaded) return <AppPageSkeleton />;
  return <Navigate replace to="/canvases" search={{ canvas: undefined }} />;
}
