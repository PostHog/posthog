import { useFeatureFlagsLoaded } from "@posthog/ui/features/feature-flags/useFeatureFlagsLoaded";
import { useSketchpadsFlag } from "@posthog/ui/features/feature-flags/useSketchpadsFlag";
import { AppPageSkeleton } from "@posthog/ui/router/routeSkeletons";
import { Navigate } from "@tanstack/react-router";
import type { ReactNode } from "react";

export function SketchpadGate({ children }: { children: ReactNode }) {
  const enabled = useSketchpadsFlag();
  const flagsLoaded = useFeatureFlagsLoaded();

  if (enabled) return children;
  if (!flagsLoaded) return <AppPageSkeleton />;
  return <Navigate replace to="/canvases" search={{ canvas: undefined }} />;
}
