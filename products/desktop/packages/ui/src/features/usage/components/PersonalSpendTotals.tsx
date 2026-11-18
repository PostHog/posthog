import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import { Text } from "@posthog/quill";
import { MetricCard, useChartTheme } from "@posthog/quill-charts";
import type { SpendSnapshot } from "@posthog/ui/features/billing/useSpendTotals";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";

interface PersonalSpendTotalsProps {
  totals: SpendSnapshot | null;
  isLoading: boolean;
}

/**
 * Your own spend, on the page without opening the detail section, so the
 * organization meter above always has a near-real-time figure beside it.
 */
export function PersonalSpendTotals({
  totals,
  isLoading,
}: PersonalSpendTotalsProps) {
  const theme = useChartTheme();

  if (isLoading) {
    return (
      <LoadingState className="rounded-(--radius-3) border border-border bg-card p-4" />
    );
  }

  if (!totals) {
    return (
      <div className="rounded-(--radius-3) border border-border bg-card p-4">
        <Text className="text-muted-foreground text-xs">
          Couldn't load your spend. In the details below, select 30 days, then
          Refresh to try again.
        </Text>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--gray-5)">
      <div className="min-w-0 bg-(--color-panel-solid) px-4 py-3">
        <MetricCard
          title={<span className="text-[12px] text-gray-11">Today</span>}
          value={Math.max(0, totals.todayUsd)}
          theme={theme}
          formatValue={formatUsd}
          change={null}
        />
      </div>
      <div className="min-w-0 bg-(--color-panel-solid) px-4 py-3">
        <MetricCard
          title={<span className="text-[12px] text-gray-11">Last 30 days</span>}
          value={Math.max(0, totals.monthUsd)}
          theme={theme}
          formatValue={formatUsd}
          change={null}
        />
      </div>
    </div>
  );
}
