import { formatUsdCompact } from "@posthog/core/billing/spendAnalysisFormat";
import {
  type SpendLimitPeriod,
  type SpendLimits,
  type SpendLimitsPatch,
  STARTER_SPEND_LINES,
} from "@posthog/core/billing/spendLimits";
import { Switch, Text } from "@posthog/quill";
import {
  clampSpendLine,
  SpendLimitSlider,
} from "@posthog/ui/features/settings/sections/SpendLimitSlider";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";

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
  onCommit: (limits: SpendLimitsPatch) => void;
  /** Lines to apply when the scope is switched on, if any can be derived. */
  suggested?: { warnUsd: number; stopUsd: number } | null;
  /** The deployment can hold a stop line. False renders and seeds the warning line only. */
  stopAvailable: boolean;
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
  stopAvailable,
}: SpendLimitCardProps) {
  const { warnUsd, stopUsd } = limits[scope];
  const effectiveStopUsd = stopAvailable ? stopUsd : null;
  const enabled = warnUsd !== null || effectiveStopUsd !== null;
  const summary =
    spentUsd !== null
      ? `${formatUsdCompact(spentUsd, { exactCents: true })}${soFarLabel ? ` ${soFarLabel}` : ""}`
      : null;

  const toggle = (next: boolean) => {
    if (!next) {
      onCommit({ [scope]: { warnUsd: null, stopUsd: null } });
      return;
    }
    // Start from the person's own history where there is any; without any,
    // round starter lines keep the scope editable rather than committing
    // nulls, which would read as the switch refusing to turn on.
    const seed = suggested ?? STARTER_SPEND_LINES[scope];
    onCommit({
      [scope]: {
        warnUsd: seed.warnUsd,
        stopUsd: stopAvailable ? seed.stopUsd : null,
      },
    });
  };

  return (
    <div className="flex flex-col gap-3 rounded-(--radius-3) border border-border bg-card px-4 py-3.5">
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
            stopUsd={effectiveStopUsd}
            spentUsd={spentUsd ?? 0}
            markerUsd={markerUsd}
            markerTitle={markerTitle}
            markerLabel={markerLabel}
            tickReferenceUsd={tickReferenceUsd}
            periodLabel={title}
            onCommit={(level, value) =>
              onCommit({
                [scope]: {
                  // The real ordering invariant: drags arrive pre-clamped, but
                  // typed input reaches here unclamped.
                  [level]: clampSpendLine(
                    level,
                    value,
                    level === "warn" ? effectiveStopUsd : warnUsd,
                  ),
                  // A stop commit is inert where the deployment cannot hold one.
                  ...(level === "stop" && !stopAvailable
                    ? { stopUsd: null }
                    : {}),
                },
              })
            }
          />
        </div>
      )}
    </div>
  );
}
