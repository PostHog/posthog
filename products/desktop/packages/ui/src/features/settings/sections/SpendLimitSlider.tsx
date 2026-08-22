import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import type { SpendLimitLevel } from "@posthog/core/billing/spendLimits";
import { useRef, useState } from "react";

export type SpendSliderTone = "ok" | "warn" | "stop";

function isPositive(value: number | null): value is number {
  return value !== null && value > 0;
}

/** Smallest 1/2/5 × 10^k at or above `value`, so the track's end is round. */
export function niceCeil(value: number): number {
  if (value <= 0) return 100;
  const exponent = Math.floor(Math.log10(value));
  const base = 10 ** exponent;
  for (const mantissa of [1, 2, 5, 10]) {
    if (value <= mantissa * base * (1 + 1e-9)) return mantissa * base;
  }
  return 10 * base;
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

export function sliderTone(
  warnUsd: number | null,
  stopUsd: number | null,
  spentUsd: number,
): SpendSliderTone {
  if (isPositive(stopUsd) && spentUsd >= stopUsd) return "stop";
  if (isPositive(warnUsd) && spentUsd >= warnUsd) return "warn";
  return "ok";
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

/** "$20" for whole dollars, "$12.40" otherwise. */
export function formatUsdCompact(value: number): string {
  if (Number.isInteger(value)) return `$${value.toLocaleString()}`;
  return formatUsd(value);
}

const FILL_CLASS: Record<SpendSliderTone, string> = {
  ok: "bg-(--blue-9)",
  warn: "bg-(--amber-9)",
  stop: "bg-(--red-9)",
};

const HANDLE_CLASS: Record<SpendLimitLevel, string> = {
  warn: "border-(--amber-9)",
  stop: "border-(--red-9)",
};

interface SpendLimitSliderProps {
  warnUsd: number | null;
  stopUsd: number | null;
  /** Spend so far in the period; 0 when unknown. */
  spentUsd: number;
  /** Optional reference marker, e.g. average per day or projected pace. */
  markerUsd: number | null;
  /** Tooltip explaining what the marker is. */
  markerTitle?: string;
  /** "Daily" or "Monthly", for the handles' accessible names. */
  periodLabel: string;
  onCommit: (level: SpendLimitLevel, value: number) => void;
}

/**
 * The lines as a draggable control: spend so far fills the track and each
 * set line is a handle that can be dragged (or arrow-keyed) to a new
 * amount. Quiet at rest — the inputs below carry the values — and a value
 * bubble follows the handle only while it moves.
 */
export function SpendLimitSlider({
  warnUsd,
  stopUsd,
  spentUsd,
  markerUsd,
  markerTitle,
  periodLabel,
  onCommit,
}: SpendLimitSliderProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{
    level: SpendLimitLevel;
    value: number;
  } | null>(null);

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
  const tone = sliderTone(liveWarn, liveStop, spentUsd);
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

  return (
    <div className="pt-5 pb-0.5">
      <div
        ref={trackRef}
        className="relative h-2.5 w-full rounded-full bg-(--gray-4)"
      >
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${settleClass} ${FILL_CLASS[tone]}`}
          style={{ width: `${percent(spentUsd)}%` }}
        />
        {isPositive(markerUsd) && (
          <div
            className={`-translate-x-1/2 absolute inset-y-0 w-[2px] rounded-full bg-(--gray-12) opacity-50 ${settleClass}`}
            style={{ left: `${percent(markerUsd)}%` }}
            title={markerTitle}
          />
        )}
        {drag && (
          <span
            className="-top-6 -translate-x-1/2 pointer-events-none absolute z-20 whitespace-nowrap rounded-(--radius-2) bg-(--gray-12) px-1.5 py-0.5 font-medium text-(--gray-1) text-[10px] tabular-nums leading-none shadow-sm"
            style={{
              left: `${Math.min(94, Math.max(5, percent(drag.value)))}%`,
            }}
          >
            {formatUsdCompact(drag.value)}
          </span>
        )}
        {handles.map((handle) => (
          <div
            key={handle.level}
            className={`-translate-x-1/2 absolute top-1/2 z-10 ${settleClass}`}
            style={{ left: `${percent(handle.value)}%` }}
          >
            {/* biome-ignore lint/a11y/useSemanticElements: a native range input cannot host two independent thumbs on one shared track */}
            <div
              role="slider"
              tabIndex={0}
              aria-label={`${periodLabel} ${handle.name} line`}
              aria-valuemin={0}
              aria-valuemax={Math.round(scale)}
              aria-valuenow={handle.value}
              aria-valuetext={formatUsd(handle.value)}
              data-attr={`spend-limit-slider-${handle.level}`}
              className={`-translate-y-1/2 block size-3.5 cursor-grab touch-none rounded-full border-2 bg-(--color-panel-solid) shadow-sm transition-transform duration-150 hover:scale-110 focus-visible:outline focus-visible:outline-(--accent-9) focus-visible:outline-2 focus-visible:outline-offset-2 active:scale-125 active:cursor-grabbing motion-reduce:transition-none ${HANDLE_CLASS[handle.level]}`}
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
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-(--gray-9) text-[9px] tabular-nums leading-none">
        <span>$0</span>
        <span>{formatUsdCompact(scale)}</span>
      </div>
    </div>
  );
}
