import type { SpendAnalysisFilledDay } from "@posthog/core/billing/spendAnalysisFormat";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/quill-charts", () => ({
  DefaultTooltip: () => null,
  TimeSeriesComboChart: () => null,
  useChartTheme: () => ({}),
}));

import { modelColorsForDays, spendSeriesForDays } from "./SpendOverTimeCard";

describe("spendSeriesForDays", () => {
  it("keeps daily spend separate from the cumulative total", () => {
    const days: SpendAnalysisFilledDay[] = [
      {
        day: "2026-08-01",
        cost_usd: 1.25,
        event_count: 1,
        input_tokens: 0,
        output_tokens: 0,
        models: [],
      },
      {
        day: "2026-08-02",
        cost_usd: -0.5,
        event_count: 2,
        input_tokens: 0,
        output_tokens: 0,
        models: [],
      },
      {
        day: "2026-08-03",
        cost_usd: 2.75,
        event_count: 3,
        input_tokens: 0,
        output_tokens: 0,
        models: [],
      },
    ];

    expect(spendSeriesForDays(days)).toMatchObject([
      { key: "daily-spend", type: "bar", data: [1.25, 0, 2.75] },
      { key: "cumulative-spend", type: "line", data: [1.25, 1.25, 4] },
    ]);
  });

  it("assigns distinct colors to each model", () => {
    const days: SpendAnalysisFilledDay[] = [
      {
        day: "2026-08-01",
        cost_usd: 0,
        event_count: 0,
        input_tokens: 0,
        output_tokens: 0,
        models: [
          {
            day: "2026-08-01",
            model: "gpt-5",
            cost_usd: 1,
            input_tokens: 1,
            output_tokens: 1,
            generation_count: 1,
          },
          {
            day: "2026-08-01",
            model: "claude-opus-4-8",
            cost_usd: 1,
            input_tokens: 1,
            output_tokens: 1,
            generation_count: 1,
          },
        ],
      },
    ];

    const colors = modelColorsForDays(days);

    expect(colors.get("gpt-5")).not.toBe(colors.get("claude-opus-4-8"));
  });
});
