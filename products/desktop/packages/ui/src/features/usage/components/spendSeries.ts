import type { SpendAnalysisFilledDay } from "@posthog/core/billing/spendAnalysisFormat";
import type { Series } from "@posthog/quill-charts";

export function spendSeriesForDays(
  filledDays: SpendAnalysisFilledDay[],
): Series[] {
  let cumulativeSpend = 0;
  const dailySpend = filledDays.map((day) => Math.max(0, day.cost_usd));

  return [
    {
      key: "daily-spend",
      label: "Daily spend",
      data: dailySpend,
      type: "bar",
      yAxisId: "daily",
    },
    {
      key: "cumulative-spend",
      label: "Cumulative spend",
      data: dailySpend.map((cost) => {
        cumulativeSpend += cost;
        return cumulativeSpend;
      }),
      type: "line",
      yAxisId: "cumulative",
      points: { radius: 3 },
    },
  ];
}
