import { useFeatureFlagsLoaded } from "@posthog/ui/features/feature-flags/useFeatureFlagsLoaded";
import { HomeView } from "@posthog/ui/features/home/HomeView";
import { useHomeEnabled } from "@posthog/ui/features/home/useHomeEnabled";
import { createFileRoute, Navigate } from "@tanstack/react-router";

// The route stays registered regardless of the flag, so a restored session or a
// persisted tab could land a flag-off user here with no Home button to leave
// by. Once flags resolve, send them to the spaces index.
function HomeRoute() {
  const flagsLoaded = useFeatureFlagsLoaded();
  const homeEnabled = useHomeEnabled();
  if (flagsLoaded && !homeEnabled) return <Navigate to="/website" replace />;
  return <HomeView />;
}

export const Route = createFileRoute("/website/home")({
  component: HomeRoute,
});
