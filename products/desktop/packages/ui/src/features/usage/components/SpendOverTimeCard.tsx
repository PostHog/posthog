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
  return (
    <TooltipSurface>
      <div className="mb-1 font-semibold opacity-60">{context.label}</div>
      {context.seriesData.map((series) => (
        <div
          key={series.series.key}
          className="flex min-w-0 items-center gap-2 rounded px-1.5 py-0.5"
        >
          <TooltipSwatch color={series.color} />
          <span className="flex-1 truncate">{series.series.label}</span>
          <strong className="tabular-nums">{formatUsd(series.value)}</strong>
        </div>
      ))}
      {day && (day.input_tokens > 0 || day.output_tokens > 0) ? (
        <div className="mt-2 border-current/25 border-t pt-1 text-center opacity-60">
          {formatTokens(day.input_tokens + day.output_tokens)} tokens
        </div>
      ) : null}
      {day?.models.length ? (
        <div className="mt-1 border-current/25 border-t pt-1">
          <div className="mb-1 px-1.5 font-semibold opacity-60">
            Model breakdown
          </div>
          <div className="max-h-40 overflow-y-auto">
            {day.models.map((model) => (
              <div key={model.model} className="rounded px-1.5 py-0.5">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="flex-1 truncate">{model.model}</span>
                  <strong className="tabular-nums">
                    {formatUsd(model.cost_usd)}
                  </strong>
                </div>
                <div className="text-xs opacity-60">
                  {formatTokens(model.input_tokens + model.output_tokens)}{" "}
                  tokens
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </TooltipSurface>
  );
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
