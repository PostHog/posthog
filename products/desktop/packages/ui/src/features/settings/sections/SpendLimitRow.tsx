import type {
  SpendLimitLevel,
  SpendLimitScope,
  SpendLimits,
} from "@posthog/core/billing/spendLimits";
import {
  clampSpendLine,
  SpendLimitSlider,
} from "@posthog/ui/features/settings/sections/SpendLimitSlider";

export const SPEND_LIMIT_KEYS: Record<
  SpendLimitScope,
  Record<SpendLimitLevel, keyof SpendLimits>
> = {
  day: { warn: "dailyWarnUsd", stop: "dailyStopUsd" },
  month: { warn: "monthlyWarnUsd", stop: "monthlyStopUsd" },
};

interface SpendLimitRowProps {
  scope: SpendLimitScope;
  /** The scope's name, for the handles' accessible names. */
  title: string;
  /** Spend so far in this scope; null when the scope has no running total. */
  spentUsd: number | null;
  /** Reference marker on the track. */
  markerUsd?: number | null;
  markerTitle?: string;
  markerLabel?: string;
  tickReferenceUsd?: number | null;
  limits: SpendLimits;
  onCommit: (limits: Partial<SpendLimits>) => void;
}

/**
 * The setter for one scope: a track whose two knobs carry their own amounts.
 * The card around it names the scope and shows its figures.
 */
export function SpendLimitRow({
  scope,
  title,
  spentUsd,
  markerUsd = null,
  markerTitle,
  markerLabel,
  tickReferenceUsd,
  limits,
  onCommit,
}: SpendLimitRowProps) {
  const warnUsd = limits[SPEND_LIMIT_KEYS[scope].warn];
  const stopUsd = limits[SPEND_LIMIT_KEYS[scope].stop];

  const commitLine = (level: SpendLimitLevel, value: number) => {
    const other = level === "warn" ? stopUsd : warnUsd;
    onCommit({
      [SPEND_LIMIT_KEYS[scope][level]]: clampSpendLine(level, value, other),
    });
  };

  return (
    <SpendLimitSlider
      warnUsd={warnUsd}
      stopUsd={stopUsd}
      spentUsd={spentUsd ?? 0}
      markerUsd={markerUsd}
      markerTitle={markerTitle}
      markerLabel={markerLabel}
      tickReferenceUsd={tickReferenceUsd}
      periodLabel={title}
      onCommit={commitLine}
    />
  );
}
