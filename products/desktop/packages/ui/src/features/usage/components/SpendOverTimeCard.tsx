import { ChartBar } from "@phosphor-icons/react";
import {
  formatTokens,
  formatUsd,
} from "@posthog/core/billing/spendAnalysisFormat";
import type { SpendAnalysisFilledDay } from "@posthog/core/billing/spendAnalysisTypes";
import type { SpendLimits } from "@posthog/core/billing/spendLimits";
import {
  type GoalLineConfig,
  type Series,
  TimeSeriesComboChart,
  type TimeSeriesComboChartConfig,
  type TooltipContext,
  TooltipSurface,
  TooltipSwatch,
  useChartTheme,
} from "@posthog/quill-charts";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { UsageCard } from "./UsageCard";

interface SpendOverTimeCardProps {
  filledDays: SpendAnalysisFilledDay[];
}

function modelLabel(model: string | null): string {
  return model ?? "Other models";
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

export function tokenTotalsForDay(
  filledDays: SpendAnalysisFilledDay[],
  dayIndex: number,
): { daily: number; cumulative: number } {
  const daysThroughSelectedDay = filledDays.slice(0, dayIndex + 1);
  const daily = daysThroughSelectedDay.at(-1);

  return {
    daily: (daily?.input_tokens ?? 0) + (daily?.output_tokens ?? 0),
    cumulative: daysThroughSelectedDay.reduce(
      (total, day) => total + day.input_tokens + day.output_tokens,
      0,
    ),
  };
}

function SpendTooltip({
  context,
  day,
  filledDays,
  modelColors,
}: {
  context: TooltipContext;
  day: SpendAnalysisFilledDay | undefined;
  filledDays: SpendAnalysisFilledDay[];
  modelColors: ReadonlyMap<string | null, string>;
}) {
  const dailySpend = context.seriesData.find(
    (series) => series.series.key === "daily-spend",
  )?.value;
  const cumulativeSpend = context.seriesData.find(
    (series) => series.series.key === "cumulative-spend",
  )?.value;
  const tokenTotals = tokenTotalsForDay(filledDays, context.dataIndex);
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
      {day?.models.length ? (
        <div className="flex items-center gap-2 px-1.5 pb-0.5 text-xs opacity-60">
          <span className="flex-1">Model</span>
          <span className="w-10 text-right">Cost</span>
          <span className="w-12 text-right">Tokens</span>
        </div>
      ) : null}
      {day?.models.map((model) => (
        <div
          key={model.model}
          className="flex min-w-0 items-center gap-2 px-1.5 py-0.5"
        >
          <TooltipSwatch
            color={modelColors.get(model.model) ?? "var(--data-color-1)"}
          />
          <span className="flex-1 truncate">{modelLabel(model.model)}</span>
          <strong className="w-10 text-right tabular-nums">
            {formatUsd(model.cost_usd)}
          </strong>
          <span className="w-12 text-right tabular-nums opacity-60">
            {formatTokens(model.input_tokens + model.output_tokens)}
          </span>
        </div>
      ))}
      <div className="mt-2 border-current/25 border-t pt-2">
        <div className="flex items-center gap-3 px-1.5 py-0.5">
          <strong className="flex-1">Daily total</strong>
          <strong className="w-10 text-right tabular-nums">
            {formatUsd(dailySpend ?? 0)}
          </strong>
          <strong className="w-12 text-right tabular-nums opacity-60">
            {formatTokens(tokenTotals.daily)}
          </strong>
        </div>
        <div className="flex items-center gap-3 px-1.5 py-0.5">
          <strong className="flex-1">Cumulative total</strong>
          <strong className="w-10 text-right tabular-nums">
            {formatUsd(cumulativeSpend ?? 0)}
          </strong>
          <strong className="w-12 text-right tabular-nums opacity-60">
            {formatTokens(tokenTotals.cumulative)}
          </strong>
        </div>
      </div>
    </TooltipSurface>
  );
}

/** The user's daily spend lines as chart goal lines on the daily axis. */
export function spendLimitGoalLines(
  limits: SpendLimits["day"],
): GoalLineConfig[] {
  const lines: GoalLineConfig[] = [];
  if (limits.warnUsd !== null) {
    lines.push({
      value: limits.warnUsd,
      label: `Warning ${formatUsd(limits.warnUsd)}`,
      color: "var(--amber-9)",
    });
  }
  if (limits.stopUsd !== null) {
    lines.push({
      value: limits.stopUsd,
      label: `Stop ${formatUsd(limits.stopUsd)}`,
      color: "var(--red-9)",
    });
  }
  return lines;
}

export function modelColorsForDays(
  filledDays: SpendAnalysisFilledDay[],
): ReadonlyMap<string | null, string> {
  const models = [
    ...new Set(
      filledDays.flatMap((day) => day.models.map((model) => model.model)),
    ),
  ].sort((a, b) => modelLabel(a).localeCompare(modelLabel(b)));

  return new Map(
    models.map((model, index) => [model, `var(--data-color-${index + 1})`]),
  );
}

export function SpendOverTimeCard({ filledDays }: SpendOverTimeCardProps) {
  const theme = useChartTheme();
  const series = spendSeriesForDays(filledDays);
  const modelColors = modelColorsForDays(filledDays);
  const spendLimits = useSettingsStore((state) => state.spendLimits);
  const goalLines = spendLimitGoalLines(spendLimits.day);

  return (
    <UsageCard
      icon={<ChartBar size={14} className="text-(--accent-9)" />}
      title="Daily spend and total"
    >
      <div className="flex h-56 w-full flex-col">
        <div className="flex items-center justify-between px-2 text-(--gray-11) text-xs">
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-sm bg-(--data-color-1)" />
            Daily spend (USD)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-(--data-color-2)" />
            Cumulative spend (USD)
          </span>
        </div>
        <div className="min-h-0 flex-1">
          <TimeSeriesComboChart
            className="h-full"
            series={series}
            labels={filledDays.map((d) => d.day)}
            config={{
              xAxis: { timezone: "UTC", interval: "day" },
              yAxis: [
                {
                  id: "daily",
                  position: "left",
                  label: "Daily spend (USD)",
                  format: "currency",
                  currency: "USD",
                },
                {
                  id: "cumulative",
                  position: "right",
                  label: "Cumulative spend (USD)",
                  format: "currency",
                  currency: "USD",
                },
              ] as unknown as TimeSeriesComboChartConfig["yAxis"],
              goalLines: goalLines.length > 0 ? goalLines : undefined,
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
                filledDays={filledDays}
                modelColors={modelColors}
              />
            )}
          />
        </div>
      </div>
    </UsageCard>
  );
}
