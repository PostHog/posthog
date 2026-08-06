import { ChartBar } from "@phosphor-icons/react";
import {
  formatTokens,
  formatUsd,
  type SpendAnalysisFilledDay,
} from "@posthog/core/billing/spendAnalysisFormat";
import {
  type Series,
  TimeSeriesComboChart,
  type TimeSeriesComboChartConfig,
  type TooltipContext,
  TooltipSurface,
  TooltipSwatch,
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

function SpendTooltip({
  context,
  day,
}: {
  context: TooltipContext;
  day: SpendAnalysisFilledDay | undefined;
}) {
  const dailySpend = context.seriesData.find(
    (series) => series.series.key === "daily-spend",
  )?.value;
  const cumulativeSpend = context.seriesData.find(
    (series) => series.series.key === "cumulative-spend",
  )?.value;
  return (
    <TooltipSurface>
      <div className="mb-2">
        <div className="font-semibold">
          {new Intl.DateTimeFormat("en-US", {
            day: "numeric",
            month: "short",
            timeZone: "UTC",
            year: "numeric",
          }).format(new Date(`${context.label}T00:00:00Z`))}
        </div>
        <div className="opacity-60">Daily breakdown</div>
      </div>
      {day?.models.map((model) => (
        <div
          key={model.model}
          className="flex min-w-0 items-center gap-2 px-1.5 py-0.5"
        >
          <TooltipSwatch color={modelColor(model.model)} />
          <span className="flex-1 truncate">{model.model}</span>
          <strong className="tabular-nums">{formatUsd(model.cost_usd)}</strong>
          <span className="tabular-nums opacity-60">
            {formatTokens(model.input_tokens + model.output_tokens)}
          </span>
        </div>
      ))}
      <div className="mt-2 border-current/25 border-t pt-2">
        <div className="flex items-center gap-3 px-1.5 py-0.5">
          <strong className="flex-1">Daily total</strong>
          <strong className="tabular-nums">{formatUsd(dailySpend ?? 0)}</strong>
        </div>
        <div className="flex items-center gap-3 px-1.5 py-0.5">
          <strong className="flex-1">Cumulative total</strong>
          <strong className="tabular-nums">
            {formatUsd(cumulativeSpend ?? 0)}
          </strong>
        </div>
      </div>
    </TooltipSurface>
  );
}

function modelColor(model: string): string {
  let hash = 0;

  for (const character of model) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  }

  return `var(--data-color-${(hash % 15) + 1})`;
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
            <SpendTooltip
              context={context}
              day={filledDays[context.dataIndex]}
            />
          )}
        />
      </div>
    </UsageCard>
  );
}
