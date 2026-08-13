import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { useFeatureFlagsLoaded } from "@posthog/ui/features/feature-flags/useFeatureFlagsLoaded";
import { HomeView } from "@posthog/ui/features/home/components/HomeView";
import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

export const Route = createFileRoute("/")({
  component: IndexRoute,
});

/**
 * How long the root route will wait for feature flags before deciding without
 * them. Long enough to cover a normal flag fetch, short enough that a reader
 * whose flags never arrive (offline, first run) still lands somewhere.
 */
const FLAG_WAIT_MS = 1_000;

/** True once the flags have arrived, or once waiting for them stopped paying. */
function useFlagsSettled(): boolean {
  const loaded = useFeatureFlagsLoaded();
  const [waited, setWaited] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setWaited(true), FLAG_WAIT_MS);
    return () => clearTimeout(timer);
  }, []);

  return loaded || waited;
}

/**
 * The root route is Home for anyone on bluebird, and the old redirect into Code
 * for everyone else.
 *
 * The decision waits for the flags rather than guessing. Redirecting first and
 * correcting later would bounce a bluebird reader through Code on every cold
 * start, and a redirect is not something a later render can take back.
 */
function IndexRoute() {
  const settled = useFlagsSettled();
  const bluebird = useBluebirdFlag();

  if (!settled) return null;
  return bluebird ? <HomeView /> : <Navigate to="/code" replace />;
}
