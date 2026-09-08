import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOpenBrowserTab } from "@posthog/ui/features/browser-tabs/useOpenBrowserTab";
import { useInboxAvailable } from "@posthog/ui/features/feature-flags/useInboxAvailable";
import { OnboardingLanding } from "@posthog/ui/features/onboarding/components/OnboardingLanding";
import { track } from "@posthog/ui/shell/analytics";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";

export const Route = createFileRoute("/_shell/onboarding-landing")({
  component: OnboardingLandingRoute,
});

function OnboardingLandingRoute() {
  const openBrowserTab = useOpenBrowserTab();
  const selfDrivingAvailable = useInboxAvailable();

  useEffect(() => {
    track(ANALYTICS_EVENTS.ONBOARDING_LANDING_VIEWED);
  }, []);

  return (
    <OnboardingLanding
      selfDrivingAvailable={selfDrivingAvailable}
      onOpenDestination={(destination, href) => {
        track(ANALYTICS_EVENTS.ONBOARDING_LANDING_DESTINATION_SELECTED, {
          destination,
        });
        openBrowserTab(href);
      }}
    />
  );
}
