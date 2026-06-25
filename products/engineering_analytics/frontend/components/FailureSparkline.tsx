import { cn } from 'lib/utils/css-classes'

export interface FailureSparklineProps {
    /** Completed runs per bucket, oldest first — total stacked bar height (volume). */
    completed: number[]
    /** Decisive failures per bucket — the red portion of each bar. Must match `completed` length. */
    failures: number[]
    /** One tooltip label per bucket; falls back to the index when omitted. Must match `completed` length. */
    labels?: string[]
    /** Accessible name for the chart (role="img"); screen readers can't read the per-bucket titles. */
    ariaLabel?: string
    /** Minimum bucket slots. When there are fewer buckets than this, the bars stay narrow and
     *  right-align (the left fills with empty track) instead of stretching fat — for the few-push
     *  PR view. Omit (the Workflows tab) to let the buckets fill the full width. */
    minSlots?: number
    className?: string
}

// The chart is drawn in a unit grid (1 unit wide per bucket, fixed height) and stretched to the
// cell with preserveAspectRatio="none", so it adapts to any window length without per-window sizing.
const VIEW_HEIGHT = 100
// Baseline sits a hair above the bottom edge so it reads as a track, not a border.
const BASELINE_Y = 96
// Top padding so the tallest bar doesn't touch the cell edge.
const TOP_PAD = 6
// Any bucket with runs clears this, so a quiet-but-active bucket is still a visible tick.
const MIN_BAR_HEIGHT = 6
// Any bucket with a failure shows at least this much red, so a single failure never disappears.
const MIN_FAIL_HEIGHT = 8
const BAR_INSET = 0.18 // leaves a gutter between bars within each unit-wide bucket

/**
 * Tiny run-status chart: one stacked bar per bucket, rising off an always-visible dotted baseline.
 * Total height is completed runs (volume); the red segment is decisive failures stacked at the
 * baseline, with successes a faint cap above. The red *fraction* reads as the failure rate — a 1%
 * day is a sliver, a 50% day is half-red — which length encodes far more accurately than shade. The
 * baseline is the point: a healthy workflow shows a clean track, so "no failures" never looks like
 * "no data".
 */
export function FailureSparkline({
    completed,
    failures,
    labels,
    ariaLabel = 'Run failure history',
    minSlots,
    className,
}: FailureSparklineProps): JSX.Element {
    const maxCompleted = Math.max(...completed, 1)
    const usableHeight = BASELINE_Y - TOP_PAD
    // Reserve at least `minSlots` columns so a handful of buckets stay narrow and sit on the right
    // (empty track to their left) rather than stretching across the whole cell.
    const slots = Math.max(completed.length, minSlots ?? 0, 1)
    const offset = slots - completed.length

    return (
        <svg
            className={cn('w-full h-8 overflow-visible', className)}
            viewBox={`0 0 ${slots} ${VIEW_HEIGHT}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={ariaLabel}
        >
            <line
                x1={0}
                y1={BASELINE_Y}
                x2={slots}
                y2={BASELINE_Y}
                stroke="var(--muted)"
                strokeWidth={1}
                strokeDasharray="1 2"
                // Keep the dotted pattern crisp despite the non-uniform x stretch.
                vectorEffect="non-scaling-stroke"
            />
            {completed.map((total, i) => {
                const fails = failures[i] ?? 0
                const barHeight = total > 0 ? Math.max(MIN_BAR_HEIGHT, (total / maxCompleted) * usableHeight) : 0
                // Red is anchored at the baseline; the muted success cap sits on top of it.
                const failHeight =
                    fails > 0 ? Math.min(barHeight, Math.max(MIN_FAIL_HEIGHT, (fails / total) * barHeight)) : 0
                const successHeight = barHeight - failHeight
                const x = offset + i + BAR_INSET
                const width = 1 - BAR_INSET * 2
                const label = labels?.[i] ?? `Bucket ${i + 1}`
                return (
                    <g key={i}>
                        {successHeight > 0 && (
                            <rect
                                x={x}
                                y={BASELINE_Y - barHeight}
                                width={width}
                                height={successHeight}
                                fill="var(--muted)"
                                fillOpacity={0.35}
                            />
                        )}
                        {failHeight > 0 && (
                            <rect
                                x={x}
                                y={BASELINE_Y - failHeight}
                                width={width}
                                height={failHeight}
                                fill="var(--danger)"
                            />
                        )}
                        {/* Full-height transparent hit area so hovering an empty bucket still shows its tooltip. */}
                        <rect x={offset + i} y={0} width={1} height={VIEW_HEIGHT} fill="transparent">
                            <title>{label}</title>
                        </rect>
                    </g>
                )
            })}
        </svg>
    )
}
