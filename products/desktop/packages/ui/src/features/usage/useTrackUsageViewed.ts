import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

export interface TrackUsageViewedInput {
  isLoading: boolean;
  isPro: boolean;
  sustainedUsedPercent: number | null;
  burstUsedPercent: number | null;
}

export function useTrackUsageViewed(input: TrackUsageViewedInput): void {
  const { isLoading, isPro, sustainedUsedPercent, burstUsedPercent } = input;

  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current) return;
    // Wait for data to settle so the once-only event doesn't lock in defaults.
    if (isLoading) return;
    firedRef.current = true;
    track(ANALYTICS_EVENTS.USAGE_VIEWED, {
      is_pro: isPro,
      sustained_used_percent: sustainedUsedPercent,
      burst_used_percent: burstUsedPercent,
    });
  }, [isLoading, isPro, sustainedUsedPercent, burstUsedPercent]);
}
