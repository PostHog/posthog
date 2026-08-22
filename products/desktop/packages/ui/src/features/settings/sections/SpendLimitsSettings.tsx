import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  projectedMonthUsd,
  type SpendLimits,
  suggestedSpendLimits,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import {
  type SpendSnapshot,
  useSpendTotals,
} from "@posthog/ui/features/billing/useSpendTotals";
import { SettingsSubsection } from "@posthog/ui/features/settings/components/SettingsSubsection";
import { SpendLimitCard } from "@posthog/ui/features/settings/sections/SpendLimitCard";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

export function SpendLimitsSettings() {
  const spendLimits = useSettingsStore((state) => state.spendLimits);
  const setSpendLimits = useSettingsStore((state) => state.setSpendLimits);
  const totals = useSpendTotals();

  return (
    <SpendLimitsSettingsView
      spendLimits={spendLimits}
      totals={totals}
      onCommit={setSpendLimits}
    />
  );
}

interface SpendLimitsSettingsViewProps {
  spendLimits: SpendLimits;
  /** Live spend for the sliders; null renders them without fill or marker. */
  totals: SpendSnapshot | null;
  onCommit: (limits: Partial<SpendLimits>) => void;
}

export function SpendLimitsSettingsView({
  spendLimits,
  totals,
  onCommit,
}: SpendLimitsSettingsViewProps) {
  const todayIso = utcDayIso();
  const avgUsd = totals && totals.avgDailyUsd > 0 ? totals.avgDailyUsd : null;
  const projectedUsd =
    avgUsd !== null ? projectedMonthUsd(avgUsd, todayIso) : null;
  const suggestion =
    avgUsd !== null ? suggestedSpendLimits(avgUsd, todayIso) : null;

  return (
    <SettingsSubsection
      title="Spend limits"
      description="A warning line notifies you. A stop line pauses new agent messages until you raise or clear it, and a turn already running always plays out."
    >
      <SpendLimitCard
        scope="day"
        title="Per day"
        description="Counts every task you run in a day, and resets at midnight UTC."
        spentUsd={totals?.todayUsd ?? null}
        soFarLabel="today"
        markerUsd={avgUsd}
        markerLabel={avgUsd !== null ? `avg ${formatUsd(avgUsd)}` : undefined}
        tickReferenceUsd={avgUsd}
        markerTitle={
          avgUsd !== null
            ? `Average per day over the last 30 days · ${formatUsd(avgUsd)}`
            : undefined
        }
        limits={spendLimits}
        onCommit={onCommit}
        suggested={
          suggestion?.dailyWarnUsd != null && suggestion.dailyStopUsd != null
            ? {
                warnUsd: suggestion.dailyWarnUsd,
                stopUsd: suggestion.dailyStopUsd,
              }
            : null
        }
      />
      <SpendLimitCard
        scope="month"
        title="Per month"
        description="Counts the whole calendar month, and resets on the first."
        spentUsd={totals?.monthUsd ?? null}
        soFarLabel="this month"
        markerUsd={projectedUsd}
        markerLabel={
          projectedUsd !== null ? `pace ${formatUsd(projectedUsd)}` : undefined
        }
        tickReferenceUsd={projectedUsd}
        markerTitle={
          projectedUsd !== null
            ? `Projected month total at your average pace · about ${formatUsd(projectedUsd)}`
            : undefined
        }
        limits={spendLimits}
        onCommit={onCommit}
        suggested={
          suggestion?.monthlyWarnUsd != null &&
          suggestion.monthlyStopUsd != null
            ? {
                warnUsd: suggestion.monthlyWarnUsd,
                stopUsd: suggestion.monthlyStopUsd,
              }
            : null
        }
      />
    </SettingsSubsection>
  );
}
