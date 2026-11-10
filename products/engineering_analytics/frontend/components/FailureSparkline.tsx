import { cn } from 'lib/utils/css-classes'

export interface FailureSparklineProps {
    /** Oldest first. */
    completed: number[]
    /** Must match `completed` length. */
    failures: number[]
    /** Must match `completed` length. */
    labels?: string[]
    ariaLabel?: string
    /** Fewer buckets than this right-align as narrow bars instead of stretching. Omit to fill the full width. */
    minSlots?: number
    className?: string
}

// The grid is one unit per bucket, stretched to the cell by preserveAspectRatio="none", so any window
// length fits without per-window sizing.
const VIEW_HEIGHT = 100
// The baseline sits above the bottom edge so it reads as a track, not a border.
const BASELINE_Y = 96
const TOP_PAD = 6
// A bucket with runs is always a visible tick.
const MIN_BAR_HEIGHT = 6
// A single failure always shows some red.
const MIN_FAIL_HEIGHT = 8
const BAR_INSET = 0.18

/** The baseline always draws, so "no failures" does not look like "no data". */
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
                // Keeps the dotted pattern crisp under the non-uniform x stretch.
                vectorEffect="non-scaling-stroke"
            />
            {completed.map((total, i) => {
                const fails = failures[i] ?? 0
                const barHeight = total > 0 ? Math.max(MIN_BAR_HEIGHT, (total / maxCompleted) * usableHeight) : 0
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
