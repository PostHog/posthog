import { ChartBar } from "@phosphor-icons/react";
import {
  formatUsd,
  type SpendAnalysisFilledDay,
} from "@posthog/core/billing/spendAnalysisFormat";
import {
  DefaultTooltip,
  type Series,
  TimeSeriesComboChart,
  type TimeSeriesComboChartConfig,
  useChartTheme,
} from "@posthog/quill-charts";
import { UsageCard } from "./UsageCard";

interface SpendOverTimeCardProps {
  filledDays: SpendAnalysisFilledDay[];
}

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

export function SpendOverTimeCard({ filledDays }: SpendOverTimeCardProps) {
  const theme = useChartTheme();
  const series = spendSeriesForDays(filledDays);

  return (
    <UsageCard
      icon={<ChartBar size={14} className="text-(--accent-9)" />}
      title="Daily spend and total"
    >
      <div className="flex h-56 w-full flex-col">
        <TimeSeriesComboChart
          series={series}
          labels={filledDays.map((d) => d.day)}
          config={{
            xAxis: { timezone: "UTC", interval: "day" },
            yAxis: [
              { id: "daily", position: "left", tickFormatter: formatUsd },
              {
                id: "cumulative",
                position: "right",
                tickFormatter: formatUsd,
              },
            ] as unknown as TimeSeriesComboChartConfig["yAxis"],
            barLayout: "grouped",
            barCornerRadius: 2,
            showCrosshair: true,
            tooltip: { placement: "cursor", showTotal: false },
          }}
          theme={theme}
          tooltip={(context) => (
            <DefaultTooltip {...context} valueFormatter={formatUsd} />
          )}
        />
      </div>
    </UsageCard>
  );
}
