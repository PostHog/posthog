import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const trackMock = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/shell/analytics", () => ({ track: trackMock }));

import {
  type TrackUsageViewedInput,
  useTrackUsageViewed,
} from "./useTrackUsageViewed";

const input = (
  overrides: Partial<TrackUsageViewedInput> = {},
): TrackUsageViewedInput => ({
  isLoading: false,
  spendTotalsLoading: false,
  sustainedUsedPercent: 0,
  burstUsedPercent: 0,
  meterKind: "dollars",
  orgUsedUsd: 12.4,
  orgLimitUsd: 70,
  personalSpend30dUsd: 41.18,
  ...overrides,
});

describe("useTrackUsageViewed", () => {
  it("carries the rendered dollars, so a figure that disagrees with personal spend is measurable", () => {
    trackMock.mockClear();
    renderHook(() => useTrackUsageViewed(input()));

    expect(trackMock).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.USAGE_VIEWED,
      expect.objectContaining({
        meter_kind: "dollars",
        org_used_usd: 12.4,
        org_limit_usd: 70,
        personal_spend_30d_usd: 41.18,
      }),
    );
  });

  it.each([41.18, 0, null])(
    "waits for usage and personal spend to settle at %s, then fires once",
    (personalSpend30dUsd) => {
      trackMock.mockClear();
      const { rerender } = renderHook(
        (props: TrackUsageViewedInput) => useTrackUsageViewed(props),
        {
          initialProps: input({
            isLoading: true,
            spendTotalsLoading: true,
            orgUsedUsd: null,
            personalSpend30dUsd: null,
          }),
        },
      );
      expect(trackMock).not.toHaveBeenCalled();

      rerender(input({ spendTotalsLoading: true, personalSpend30dUsd: null }));
      expect(trackMock).not.toHaveBeenCalled();

      rerender(input({ personalSpend30dUsd }));
      rerender(input({ orgUsedUsd: 13.9 }));
      expect(trackMock).toHaveBeenCalledTimes(1);
      expect(trackMock).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.USAGE_VIEWED,
        expect.objectContaining({
          org_used_usd: 12.4,
          personal_spend_30d_usd: personalSpend30dUsd,
        }),
      );
    },
  );
});
