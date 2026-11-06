import {
  formatUsd,
  formatUsdCompact,
} from "@posthog/core/billing/spendAnalysisFormat";
import {
  niceCeil,
  type SpendLimitLevel,
  spendTickIncrement,
} from "@posthog/core/billing/spendLimits";
import { SpendKnobValue } from "@posthog/ui/features/settings/sections/SpendKnobValue";
import { useRef, useState } from "react";

function isPositive(value: number | null): value is number {
  return value !== null && value > 0;
}

/**
 * The track's dollar range, kept stable across small edits: it grows the
 * moment a value passes the top, but shrinks only once everything sits far
 * below it. Without the hysteresis every drag release would rescale the
 * track and make all the handles jump.
 */
export function resolveScale(previous: number | null, needed: number): number {
  const target = niceCeil(needed);
  if (previous === null || previous <= 0) return target;
  if (needed > previous) return target;
  if (needed < previous * 0.4) return target;
  return previous;
}

/** Drag granularity grows with the track's range so values stay round. */
export function sliderStep(scale: number): number {
  if (scale <= 30) return 0.5;
  if (scale <= 120) return 1;
  if (scale <= 600) return 5;
  return 10;
}

/**
 * Keeps the pair ordered: the warning line never sits above the stop line.
 * Applied on every commit path (drag, keys, inputs) so the invariant holds
 * no matter how a value arrives.
 */
export function clampSpendLine(
  level: SpendLimitLevel,
  value: number,
  otherUsd: number | null,
): number {
  if (!isPositive(otherUsd)) return value;
  if (level === "warn") return Math.min(value, otherUsd);
  return Math.max(value, otherUsd);
}

interface SpendLimitSliderProps {
  warnUsd: number | null;
  stopUsd: number | null;
  /** Spend so far in the period; 0 when unknown. */
  spentUsd: number;
  /** Optional reference marker, e.g. average per day or projected pace. */
  markerUsd: number | null;
  /** Tooltip explaining what the marker is. */
  markerTitle?: string;
  /** Short label under the marker, e.g. "avg $12.40". */
  markerLabel?: string;
  /**
   * The figure tick spacing is anchored to, so a tick reads as roughly a day's
   * average or a month's pace rather than an arbitrary slice of the track.
   */
  tickReferenceUsd?: number | null;
  /** "Daily" or "Monthly", for the handles' accessible names. */
  periodLabel: string;
  onCommit: (level: SpendLimitLevel, value: number) => void;
}

/**
 * The lines as a draggable control: spend so far fills the track and each
 * set line is a handle that can be dragged (or arrow-keyed) to a new
 * amount. The track carries no labels at rest, since the inputs below hold the
 * values, and a value bubble follows the handle only while it moves.
 */
export function SpendLimitSlider({
  warnUsd,
  stopUsd,
  spentUsd,
  markerUsd,
  markerTitle,
  markerLabel,
  tickReferenceUsd,
  periodLabel,
  onCommit,
}: SpendLimitSliderProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{
    level: SpendLimitLevel;
    value: number;
  } | null>(null);

  // A preempted pointer (trackpad or touch gesture the browser cancels
  // mid-drag, or lost capture) must drop the live drag without committing, so
  // the handle stops tracking the cursor and the callout falls back to the
  // saved line. Mirrors the grid-drag cleanup.
  const cancelDrag = (level: SpendLimitLevel) => {
    setDrag((current) => (current?.level === level ? null : current));
  };

  const liveWarn = drag?.level === "warn" ? drag.value : warnUsd;
  const liveStop = drag?.level === "stop" ? drag.value : stopUsd;

  const needed =
    Math.max(...[warnUsd, stopUsd, markerUsd, spentUsd].filter(isPositive), 0) *
    1.1;
  const [scale, setScale] = useState(() => resolveScale(null, needed || 90));
  // Derive during render, never mid-drag: rescaling under a moving handle
  // would shift every other handle with it.
  if (drag === null) {
    const next = resolveScale(scale, needed || 90);
    if (next !== scale) setScale(next);
  }

  const step = sliderStep(scale);
  const percent = (value: number) =>
    Math.min(100, Math.max(0, (value / scale) * 100));
  const settleClass = drag
    ? ""
    : "transition-[left,width,background-color] duration-300 motion-reduce:transition-none";

  const otherLine = (level: SpendLimitLevel): number | null =>
    level === "warn" ? stopUsd : warnUsd;

  const valueFromPointer = (
    level: SpendLimitLevel,
    clientX: number,
  ): number => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return step;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const snapped = Math.max(step, Math.round((ratio * scale) / step) * step);
    return clampSpendLine(level, snapped, otherLine(level));
  };

  const handles: {
    level: SpendLimitLevel;
    value: number;
    name: string;
  }[] = [];
  if (isPositive(liveWarn)) {
    handles.push({ level: "warn", value: liveWarn, name: "warning" });
  }
  if (isPositive(liveStop)) {
    handles.push({ level: "stop", value: liveStop, name: "stop" });
  }
  // With no lines yet, the track still shows spend and the reference marker,
  // so the suggestion above has something visual to anchor to.
  if (handles.length === 0 && spentUsd <= 0 && !isPositive(markerUsd)) {
    return null;
  }

  const warnPercent = isPositive(liveWarn) ? percent(liveWarn) : null;
  const stopPercent = isPositive(liveStop) ? percent(liveStop) : null;
  // Zones read left to right: fine up to the warning, caution up to the stop,
  // and the tail past the stop is where spend cannot go.
  const tickIncrement = spendTickIncrement(scale, tickReferenceUsd ?? null);
  const tickPercents: number[] = [];
  if (tickIncrement > 0) {
    for (let value = tickIncrement; value < scale; value += tickIncrement) {
      tickPercents.push(percent(value));
    }
  }
  const cautionStart = warnPercent ?? 0;
  const cautionWidth = Math.max(
    0,
    (stopPercent ?? cautionStart) - cautionStart,
  );

  return (
    <div className="pt-10 pb-1">
      <div ref={trackRef} className="relative h-3.5 w-full">
        <div className="absolute inset-0 overflow-hidden rounded-full bg-(--gray-4)">
          {/* One colored band, between the warning and the stop. Everything
              else is the track's own gray, so color only ever means caution. */}
          {cautionWidth > 0 && (
            <div
              className={`absolute inset-y-0 bg-(--amber-9) ${settleClass}`}
              style={{ left: `${cautionStart}%`, width: `${cautionWidth}%` }}
            />
          )}
          {stopPercent !== null && (
            <div
              className={`absolute inset-y-0 right-0 bg-(--red-9) ${settleClass}`}
              style={{ left: `${stopPercent}%` }}
            />
          )}
          {/* A ruler: one dot per increment, so a position on the track can be
              read rather than guessed. */}
          {tickPercents.map((tickPercent) => (
            <span
              key={tickPercent}
              aria-hidden="true"
              className="-translate-x-1/2 -translate-y-1/2 absolute top-1/2 size-[3px] rounded-full bg-(--gray-a7)"
              style={{ left: `${tickPercent}%` }}
            />
          ))}
          {/* Spend so far: a drifting hatch, so a live figure reads as live
              without competing with the caution band for meaning. */}
          {spentUsd > 0 && (
            <div
              aria-hidden="true"
              className={`absolute inset-y-0 left-0 animate-[spend-usage-drift_1.1s_linear_infinite] bg-(--gray-6) [background-image:repeating-linear-gradient(115deg,rgba(255,255,255,0.5)_0_2px,transparent_2px_6px)] motion-reduce:animate-none ${settleClass}`}
              style={{ width: `${percent(spentUsd)}%` }}
            />
          )}
        </div>
        {isPositive(markerUsd) && (
          <div
            className={`-translate-x-1/2 absolute inset-y-0 w-[2px] rounded-full bg-(--gray-12) opacity-40 ${settleClass}`}
            style={{ left: `${percent(markerUsd)}%` }}
            title={markerTitle}
          />
        )}
        {handles.map((handle) => (
          <span
            key={`${handle.level}-value`}
            className={`-top-9 -translate-x-1/2 absolute z-20 whitespace-nowrap ${settleClass}`}
            style={{
              left: `${Math.min(94, Math.max(6, percent(handle.value)))}%`,
            }}
          >
            <SpendKnobValue
              valueUsd={handle.value}
              label={formatUsdCompact(handle.value)}
              name={`${periodLabel} ${handle.name} line`}
              onCommit={(value) => onCommit(handle.level, value)}
            />
          </span>
        ))}
        {handles.map((handle) => (
          <div
            key={handle.level}
            className={`-translate-x-1/2 absolute top-1/2 z-10 ${settleClass}`}
            style={{ left: `${percent(handle.value)}%` }}
          >
            <div
              role="slider"
              tabIndex={0}
              aria-label={`${periodLabel} ${handle.name} line`}
              aria-valuemin={0}
              aria-valuemax={Math.round(scale)}
              aria-valuenow={handle.value}
              aria-valuetext={formatUsd(handle.value)}
              data-attr={`spend-limit-slider-${handle.level}`}
              // A larger transparent hit area around a notch the size of the
              // track, so the handle sits inside the color rather than on it.
              className="-translate-y-1/2 flex size-6 cursor-grab touch-none items-center justify-center rounded-full focus-visible:outline focus-visible:outline-(--accent-9) focus-visible:outline-2 focus-visible:outline-offset-1 active:cursor-grabbing"
              onPointerDown={(event) => {
                event.preventDefault();
                event.currentTarget.setPointerCapture(event.pointerId);
                setDrag({ level: handle.level, value: handle.value });
              }}
              onPointerMove={(event) => {
                if (drag?.level !== handle.level) return;
                setDrag({
                  level: handle.level,
                  value: valueFromPointer(handle.level, event.clientX),
                });
              }}
              onPointerUp={() => {
                if (drag?.level !== handle.level) return;
                onCommit(handle.level, drag.value);
                setDrag(null);
              }}
              onPointerCancel={() => cancelDrag(handle.level)}
              onLostPointerCapture={() => cancelDrag(handle.level)}
              onKeyDown={(event) => {
                const direction =
                  event.key === "ArrowRight" || event.key === "ArrowUp"
                    ? 1
                    : event.key === "ArrowLeft" || event.key === "ArrowDown"
                      ? -1
                      : 0;
                if (direction === 0) return;
                event.preventDefault();
                const next = clampSpendLine(
                  handle.level,
                  Math.max(step, handle.value + direction * step),
                  otherLine(handle.level),
                );
                if (next !== handle.value) onCommit(handle.level, next);
              }}
            >
              <span
                aria-hidden="true"
                className="size-3.5 rounded-full bg-[#fff] shadow-[0_1px_2px_rgba(0,0,0,0.3)] transition-transform duration-150 motion-reduce:transition-none"
              />
            </div>
          </div>
        ))}
      </div>
      <div className="relative mt-2 h-3">
        <span className="absolute left-0 whitespace-nowrap text-(--gray-11) text-[9.5px] tabular-nums leading-none">
          {spentUsd > 0 ? `${formatUsdCompact(spentUsd)} spent` : "$0"}
        </span>
        {isPositive(markerUsd) && markerLabel && (
          <span
            className={`-translate-x-1/2 absolute whitespace-nowrap text-(--gray-11) text-[9.5px] tabular-nums leading-none ${settleClass}`}
            style={{
              left: `${Math.min(88, Math.max(8, percent(markerUsd)))}%`,
            }}
            title={markerTitle}
          >
            {markerLabel}
          </span>
        )}
        <span className="absolute right-0 text-(--gray-9) text-[9px] tabular-nums leading-none">
          {formatUsdCompact(scale)}
        </span>
      </div>
    </div>
  );
}
