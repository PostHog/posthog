import {
  formatUsd,
  formatWindow,
  type SpendAnalysisFilledDay,
  windowDays,
} from "@posthog/core/billing/spendAnalysisFormat";
import type { SpendAnalysisResponse } from "@posthog/core/billing/spendAnalysisTypes";
import { MetricCard, useChartTheme } from "@posthog/quill-charts";
import { Flex } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { spendDayLabel } from "./spendDayLabel";

const tileTitle = (label: string): ReactNode => (
  <span className="text-[11px] text-gray-10 uppercase tracking-wide">
    {label}
  </span>
);

function KpiCell({ children, last }: { children: ReactNode; last?: boolean }) {
  return (
    <div
      className={`min-w-0 flex-1 px-4 py-3 ${last ? "" : "border-(--gray-5) border-r"}`}
    >
      {children}
    </div>
  );
}

interface SpendKpiStripProps {
  data: SpendAnalysisResponse;
  filledDays: SpendAnalysisFilledDay[] | null;
}

export function SpendKpiStrip({ data, filledDays }: SpendKpiStripProps) {
  const theme = useChartTheme();
  const { summary } = data;
  const labels = filledDays?.map((d) => spendDayLabel(d.day));
  const costSeries = filledDays?.map((d) => Math.max(0, d.cost_usd));
  const eventSeries = filledDays?.map((d) => d.event_count);
  const latestDay = filledDays?.at(-1);
  const windowLabel = formatWindow(summary.date_from, summary.date_to);

  return (
    <Flex className="overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid)">
      <KpiCell>
        <MetricCard
          title={tileTitle("Total spend")}
          value={Math.max(0, summary.total_cost_usd)}
          theme={theme}
          formatValue={formatUsd}
          change={null}
          subtitle="All AI products"
        />
      </KpiCell>
      <KpiCell>
        <MetricCard
          title={tileTitle("This app")}
          value={Math.max(0, summary.scoped_cost_usd)}
          data={costSeries}
          labels={labels}
          theme={theme}
          formatValue={formatUsd}
          change={null}
          restingSubtitle={windowLabel}
          sparklineHeight={28}
        />
      </KpiCell>
      <KpiCell>
        <MetricCard
          title={tileTitle("Generations")}
          value={summary.scoped_event_count}
          data={eventSeries}
          labels={labels}
          theme={theme}
          formatValue={(v) => v.toLocaleString()}
          change={null}
          restingSubtitle={windowLabel}
          sparklineHeight={28}
        />
      </KpiCell>
      <KpiCell last>
        {latestDay ? (
          <MetricCard
            title={tileTitle("Latest day")}
            value={Math.max(0, latestDay.cost_usd)}
            theme={theme}
            formatValue={formatUsd}
            change={null}
            subtitle={spendDayLabel(latestDay.day)}
          />
        ) : (
          <MetricCard
            title={tileTitle("Window")}
            value={windowDays(summary.date_from, summary.date_to)}
            theme={theme}
            formatValue={(v) => `${v} days`}
            change={null}
          />
        )}
      </KpiCell>
    </Flex>
  );
}
