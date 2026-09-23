import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import { Text } from "@posthog/quill";
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
  if (isLoading) {
    return (
      <LoadingState className="rounded-(--radius-3) border border-border bg-card p-4" />
    );
  }

  if (!totals) {
    return (
      <div className="rounded-(--radius-3) border border-border bg-card p-4">
        <Text className="text-muted-foreground text-xs">
          Couldn't load your spend. Use Refresh in the details below to try
          again.
        </Text>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-8 rounded-(--radius-3) border border-border bg-card p-4">
      <SpendTotal label="Today" valueUsd={totals.todayUsd} />
      <SpendTotal label="Last 30 days" valueUsd={totals.monthUsd} />
    </div>
  );
}

function SpendTotal({ label, valueUsd }: { label: string; valueUsd: number }) {
  return (
    <div className="flex flex-col gap-1">
      <Text className="text-muted-foreground text-xs">{label}</Text>
      <Text className="font-medium text-foreground text-sm">
        {formatUsd(Math.max(0, valueUsd))}
      </Text>
    </div>
  );
}
