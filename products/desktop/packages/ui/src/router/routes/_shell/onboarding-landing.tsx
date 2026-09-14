import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAutoresearchEnabled } from "@posthog/ui/features/autoresearch/useAutoresearchEnabled";
import { useOpenBrowserTab } from "@posthog/ui/features/browser-tabs/useOpenBrowserTab";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useInboxAvailable } from "@posthog/ui/features/feature-flags/useInboxAvailable";
import {
  type OnboardingDebugOverrides,
  OnboardingDebugToggles,
} from "@posthog/ui/features/onboarding/components/OnboardingDebugToggles";
import { OnboardingLanding } from "@posthog/ui/features/onboarding/components/OnboardingLanding";
import { track } from "@posthog/ui/shell/analytics";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

export const Route = createFileRoute("/_shell/onboarding-landing")({
  component: OnboardingLandingRoute,
});

// Until the channel list loads, a task opens in the default new task view.
function newTaskHref(channel: { id: string } | undefined): string {
  return channel ? `/spaces/${channel.id}/new` : "/new";
}

function OnboardingLandingRoute() {
  const openBrowserTab = useOpenBrowserTab();
  const selfDrivingAvailable = useInboxAvailable();
  const autoresearchAvailable = useAutoresearchEnabled();
  const { generalChannel, personalChannel } = useTaskChannels();
  const [debugOverrides, setDebugOverrides] =
    useState<OnboardingDebugOverrides>({
      selfDrivingOff: false,
      autoresearchOff: false,
    });

  useEffect(() => {
    track(ANALYTICS_EVENTS.ONBOARDING_LANDING_VIEWED);
  }, []);

  return (
    <div className="relative h-full">
      {import.meta.env.DEV && (
        <OnboardingDebugToggles
          overrides={debugOverrides}
          onChange={setDebugOverrides}
        />
      )}
      <OnboardingLanding
        selfDrivingAvailable={
          selfDrivingAvailable && !debugOverrides.selfDrivingOff
        }
        autoresearchAvailable={
          autoresearchAvailable && !debugOverrides.autoresearchOff
        }
        taskSpaceHrefs={{
          general: newTaskHref(generalChannel),
          personal: newTaskHref(personalChannel),
        }}
        onOpenDestination={(destination, href) => {
          track(ANALYTICS_EVENTS.ONBOARDING_LANDING_DESTINATION_SELECTED, {
            destination,
          });
          openBrowserTab(href);
        }}
      />
    </div>
  );
}
