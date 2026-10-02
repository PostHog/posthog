import {
  ANALYTICS_EVENTS,
  type UsageViewedProperties,
} from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

export interface TrackUsageViewedInput {
  isLoading: boolean;
  spendTotalsLoading: boolean;
  sustainedUsedPercent: number | null;
  burstUsedPercent: number | null;
  meterKind: UsageViewedProperties["meter_kind"];
  orgUsedUsd: number | null;
  orgLimitUsd: number | null;
  personalSpend30dUsd: number | null;
}

export function useTrackUsageViewed(input: TrackUsageViewedInput): void {
  const {
    isLoading,
    spendTotalsLoading,
    sustainedUsedPercent,
    burstUsedPercent,
    meterKind,
    orgUsedUsd,
    orgLimitUsd,
    personalSpend30dUsd,
  } = input;

  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current) return;
    // Wait for data to settle so the once-only event doesn't lock in defaults.
    if (isLoading || spendTotalsLoading) return;
    firedRef.current = true;
    track(ANALYTICS_EVENTS.USAGE_VIEWED, {
      sustained_used_percent: sustainedUsedPercent,
      burst_used_percent: burstUsedPercent,
      meter_kind: meterKind,
      org_used_usd: orgUsedUsd,
      org_limit_usd: orgLimitUsd,
      personal_spend_30d_usd: personalSpend30dUsd,
    });
  }, [
    isLoading,
    spendTotalsLoading,
    sustainedUsedPercent,
    burstUsedPercent,
    meterKind,
    orgUsedUsd,
    orgLimitUsd,
    personalSpend30dUsd,
  ]);
}
