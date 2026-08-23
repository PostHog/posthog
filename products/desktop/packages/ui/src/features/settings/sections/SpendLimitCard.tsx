import type {
  SpendLimitLevel,
  SpendLimitPeriod,
  SpendLimits,
} from "@posthog/core/billing/spendLimits";
import { Switch, Text } from "@posthog/quill";
import {
  clampSpendLine,
  SpendLimitSlider,
} from "@posthog/ui/features/settings/sections/SpendLimitSlider";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";

const SPEND_LIMIT_KEYS: Record<
  SpendLimitPeriod,
  Record<SpendLimitLevel, keyof SpendLimits>
> = {
  day: { warn: "dailyWarnUsd", stop: "dailyStopUsd" },
  month: { warn: "monthlyWarnUsd", stop: "monthlyStopUsd" },
};

interface SpendLimitCardProps {
  scope: SpendLimitPeriod;
  title: string;
  /** Spend so far in this scope; null when it has no running total. */
  spentUsd: number | null;
  /** What the figure counts, e.g. "today". */
  soFarLabel?: string;
  /** Subheader under the title, saying what the scope counts. */
  description: string;
  markerUsd?: number | null;
  markerTitle?: string;
  markerLabel?: string;
  tickReferenceUsd?: number | null;
  limits: SpendLimits;
  onCommit: (limits: Partial<SpendLimits>) => void;
  /** Lines to apply when the scope is switched on, if any can be derived. */
  suggested?: { warnUsd: number; stopUsd: number } | null;
}

/**
 * One scope's limit, on its own switch. Off means both of its lines are clear,
 * so the switch is the scope's state rather than a separate setting that could
 * disagree with it. The setter only appears once it is on.
 */
export function SpendLimitCard({
  scope,
  title,
  spentUsd,
  soFarLabel,
  description,
  markerUsd = null,
  markerTitle,
  markerLabel,
  tickReferenceUsd,
  limits,
  onCommit,
  suggested = null,
}: SpendLimitCardProps) {
  const warnKey = SPEND_LIMIT_KEYS[scope].warn;
  const stopKey = SPEND_LIMIT_KEYS[scope].stop;
  const warnUsd = limits[warnKey];
  const stopUsd = limits[stopKey];
  const enabled = warnUsd !== null || stopUsd !== null;
  const summary =
    spentUsd !== null
      ? `${formatSpent(spentUsd)}${soFarLabel ? ` ${soFarLabel}` : ""}`
      : null;

  const toggle = (next: boolean) => {
    if (!next) {
      onCommit({ [warnKey]: null, [stopKey]: null });
      return;
    }
    // Start from the person's own history where there is any; otherwise the
    // fields open empty rather than showing a number we invented.
    onCommit({
      [warnKey]: suggested?.warnUsd ?? null,
      [stopKey]: suggested?.stopUsd ?? null,
    });
  };

  return (
    <div className="flex flex-col gap-3 rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) px-4 py-3.5">
      <div className="flex items-center justify-between gap-4">
        <span className="flex min-w-0 flex-col gap-0.5">
          <Text className="text-(--gray-12) text-[13px]">{title}</Text>
          <Text className="text-(--gray-11) text-[12px]">
            {description}
            {/* Only while off: once on, the track's own legend carries the
                figures, and saying them twice reads as clutter. */}
            {!enabled && summary && (
              <>
                {" "}
                <button
                  type="button"
                  className="cursor-pointer border-(--gray-8) border-0 border-b border-dashed bg-transparent p-0 text-(--gray-11) text-[12px] tabular-nums hover:text-(--gray-12)"
                  onClick={() => navigateToSettings("plan-usage")}
                  title="See where this went"
                  data-attr={`spend-limit-${scope}-spent`}
                >
                  {summary}
                </button>
                .
              </>
            )}
          </Text>
        </span>
        <Switch
          checked={enabled}
          onCheckedChange={toggle}
          aria-label={`${title} spend limit`}
          data-attr={`spend-limit-${scope}-toggle`}
        />
      </div>
      {enabled && (
        <div className="border-(--gray-4) border-t border-dashed pt-3.5">
          <SpendLimitSlider
            warnUsd={warnUsd}
            stopUsd={stopUsd}
            spentUsd={spentUsd ?? 0}
            markerUsd={markerUsd}
            markerTitle={markerTitle}
            markerLabel={markerLabel}
            tickReferenceUsd={tickReferenceUsd}
            periodLabel={title}
            onCommit={(level, value) =>
              onCommit({
                [SPEND_LIMIT_KEYS[scope][level]]: clampSpendLine(
                  level,
                  value,
                  level === "warn" ? stopUsd : warnUsd,
                ),
              })
            }
          />
        </div>
      )}
    </div>
  );
}

/** Whole dollars for the large running totals, cents for small ones. */
function formatSpent(value: number): string {
  if (value >= 1000) return `$${Math.round(value).toLocaleString("en-US")}`;
  return `$${value.toFixed(2)}`;
}
