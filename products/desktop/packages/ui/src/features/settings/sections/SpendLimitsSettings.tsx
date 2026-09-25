import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  projectedMonthUsd,
  type SpendLimits,
  type SpendLimitsPatch,
  suggestedSpendLimits,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import {
  type SpendSnapshot,
  useSpendTotals,
} from "@posthog/ui/features/billing/useSpendTotals";
import {
  USER_SPEND_LIMIT_FLAG,
  USER_SPEND_LIMIT_QUERY_KEY,
  useSetUserSpendLimit,
  useUserSpendLimit,
} from "@posthog/ui/features/billing/useUserSpendLimit";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SettingsSubsection } from "@posthog/ui/features/settings/components/SettingsSubsection";
import { SpendLimitCard } from "@posthog/ui/features/settings/sections/SpendLimitCard";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

/**
 * The window the stop line resets over. The gateway counts a fixed window
 * that starts at the first spend after a reset, so this is 30 days of spend
 * rather than a calendar month.
 */
const MONTH_WINDOW_SECONDS = 30 * 24 * 60 * 60;

export function SpendLimitsSettings() {
  const enabled = useFeatureFlag(USER_SPEND_LIMIT_FLAG);
  const spendLimits = useSettingsStore((state) => state.spendLimits);
  const setSpendLimits = useSettingsStore((state) => state.setSpendLimits);
  const totals = useSpendTotals();
  const spendLimit = useUserSpendLimit();
  const pushLimit = useSetUserSpendLimit();
  const queryClient = useQueryClient();
  const serverLimitUsd = spendLimit.data?.available
    ? (spendLimit.data.limitUsd ?? null)
    : undefined;

  // The gateway holds the line whether this app is running or not, so its
  // stored value is the truth a stale local one has to give way to. Keyed on
  // the fetched value alone: a local edit is pushed below, and reacting to it
  // here would fight the person typing.
  useEffect(() => {
    if (serverLimitUsd === undefined) return;
    setSpendLimits({ month: { stopUsd: serverLimitUsd } });
  }, [serverLimitUsd, setSpendLimits]);

  const commit = (limits: SpendLimitsPatch) => {
    setSpendLimits(limits);
    if (
      !limits.month ||
      !("stopUsd" in limits.month) ||
      !spendLimit.data?.available
    ) {
      return;
    }
    pushLimit.mutate(
      {
        limitUsd: limits.month.stopUsd ?? null,
        windowSeconds: MONTH_WINDOW_SECONDS,
      },
      {
        onError: (error) => {
          // The gateway still holds its old line, so put the store back on it
          // and refetch; otherwise the card would show a stop the gateway
          // never accepted, and the reconcile effect above would not re-fire.
          setSpendLimits({ month: { stopUsd: serverLimitUsd ?? null } });
          queryClient.invalidateQueries({
            queryKey: USER_SPEND_LIMIT_QUERY_KEY,
          });
          toast.error("Couldn't save your stop line", {
            description:
              error instanceof Error ? error.message : "Try again in a moment.",
          });
        },
      },
    );
  };

  if (!enabled) {
    return null;
  }

  return (
    <SpendLimitsSettingsView
      spendLimits={spendLimits}
      totals={totals}
      stopAvailable={spendLimit.data?.available ?? false}
      onCommit={commit}
    />
  );
}

interface SpendLimitsSettingsViewProps {
  spendLimits: SpendLimits;
  /** Live spend for the sliders; null renders them without fill or marker. */
  totals: SpendSnapshot | null;
  /** The deployment can hold a stop line; without it only warning lines are offered. */
  stopAvailable: boolean;
  onCommit: (limits: SpendLimitsPatch) => void;
}

export function SpendLimitsSettingsView({
  spendLimits,
  totals,
  stopAvailable,
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
      description={
        stopAvailable
          ? "A warning line notifies you; a stop line pauses new agent messages until you raise or clear it, and a turn already running always plays out; lines count model spend, not sandbox compute"
          : "A warning line notifies you when spend passes it, and a turn already running always plays out; lines count model spend, not sandbox compute"
      }
    >
      <SpendLimitCard
        scope="day"
        title="Per day"
        description="Counts every task you run in a day, and resets at midnight UTC"
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
        suggested={suggestion?.day ?? null}
        stopAvailable={stopAvailable}
      />
      <SpendLimitCard
        scope="month"
        title="Per month"
        description={
          stopAvailable
            ? "Counts 30 days of model spend, and restarts once the window runs out"
            : "Counts the whole calendar month, and resets on the first"
        }
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
        suggested={suggestion?.month ?? null}
        stopAvailable={stopAvailable}
      />
    </SettingsSubsection>
  );
}
