import { ChartBar } from "@phosphor-icons/react";
import {
  formatUsd,
  type SpendAnalysisFilledDay,
} from "@posthog/core/billing/spendAnalysisFormat";
import {
  type Series,
  TimeSeriesBarChart,
  useChartTheme,
} from "@posthog/quill-charts";
import { UsageCard } from "./UsageCard";

const VALUE_LABEL_MAX_BARS = 31;

interface SpendOverTimeCardProps {
  filledDays: SpendAnalysisFilledDay[];
}

export function SpendOverTimeCard({ filledDays }: SpendOverTimeCardProps) {
  const theme = useChartTheme();
  const series: Series[] = [
    {
      key: "cost",
      label: "Cost (USD)",
      data: filledDays.map((d) => Math.max(0, d.cost_usd)),
    },
  ];
  const showValueLabels = filledDays.length <= VALUE_LABEL_MAX_BARS;
  return (
    <UsageCard
      icon={<ChartBar size={14} className="text-(--accent-9)" />}
      title="Cost over time"
    >
      {/* flex-col + fixed height: the quill chart sizes its canvas by filling
          a flex-column parent; a plain block collapses it to 0. */}
      <div className="flex h-56 w-full flex-col">
        <TimeSeriesBarChart
          series={series}
          labels={filledDays.map((d) => d.day)}
          config={{
            xAxis: { timezone: "UTC", interval: "day" },
            yAxis: { tickFormatter: formatUsd },
            valueLabels: showValueLabels
              ? { formatter: (value) => (value > 0 ? formatUsd(value) : "") }
              : false,
            barCornerRadius: 2,
            showCrosshair: true,
          }}
          theme={theme}
        />
      </div>
    </UsageCard>
  );
}
