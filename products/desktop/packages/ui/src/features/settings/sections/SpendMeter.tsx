export type SpendMeterTone = "ok" | "warn" | "alert";

export interface SpendMeterLayout {
  fillPercent: number;
  warnPercent: number | null;
  alertPercent: number | null;
  tone: SpendMeterTone;
}

/**
 * Positions the fill and the line ticks on a shared scale with headroom past
 * the highest value, so a tick never sits flush against the track's end.
 * Null when no line is set, since there is nothing to measure against.
 */
export function spendMeterLayout(
  warnUsd: number | null,
  alertUsd: number | null,
  spentUsd: number,
): SpendMeterLayout | null {
  const lines = [warnUsd, alertUsd].filter(
    (value): value is number => value !== null && value > 0,
  );
  if (lines.length === 0) return null;
  const scale = Math.max(...lines, spentUsd) * 1.12;
  const percent = (value: number) =>
    Math.min(100, Math.max(0, (value / scale) * 100));
  const tone: SpendMeterTone =
    alertUsd !== null && alertUsd > 0 && spentUsd >= alertUsd
      ? "alert"
      : warnUsd !== null && warnUsd > 0 && spentUsd >= warnUsd
        ? "warn"
        : "ok";
  return {
    fillPercent: spentUsd > 0 ? percent(spentUsd) : 0,
    warnPercent: warnUsd !== null && warnUsd > 0 ? percent(warnUsd) : null,
    alertPercent: alertUsd !== null && alertUsd > 0 ? percent(alertUsd) : null,
    tone,
  };
}

const FILL_CLASS: Record<SpendMeterTone, string> = {
  ok: "bg-(--gray-8)",
  warn: "bg-(--amber-9)",
  alert: "bg-(--red-9)",
};

/**
 * Spend against the user's lines: a quiet track, a fill that takes the color
 * of the highest line crossed, and one tick per line in that line's color.
 */
export function SpendMeter({
  layout,
  label,
}: {
  layout: SpendMeterLayout;
  label: string;
}) {
  return (
    <div
      role="img"
      aria-label={label}
      className="relative h-1.5 w-full rounded-full bg-(--gray-4)"
    >
      <div
        className={`absolute inset-y-0 left-0 rounded-full transition-[width] duration-500 motion-reduce:transition-none ${FILL_CLASS[layout.tone]}`}
        style={{ width: `${layout.fillPercent}%` }}
      />
      {layout.warnPercent !== null && (
        <div
          className="-inset-y-1 absolute w-0.5 rounded-full bg-(--amber-9)"
          style={{ left: `${layout.warnPercent}%` }}
        />
      )}
      {layout.alertPercent !== null && (
        <div
          className="-inset-y-1 absolute w-0.5 rounded-full bg-(--red-9)"
          style={{ left: `${layout.alertPercent}%` }}
        />
      )}
    </div>
  );
}
