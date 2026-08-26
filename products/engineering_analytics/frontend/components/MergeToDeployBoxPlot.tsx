import { cn } from 'lib/utils/css-classes'

export interface BoxPlotBucket {
    /** Tooltip label for the bucket (e.g. its date). */
    label: string
    /** Samples in the bucket; 0 renders an empty slot on the baseline. */
    count: number
    minSeconds: number | null
    p25Seconds: number | null
    p50Seconds: number | null
    p75Seconds: number | null
    p90Seconds: number | null
    maxSeconds: number | null
}

export interface MergeToDeployBoxPlotProps {
    /** One entry per bucket, oldest first. */
    buckets: BoxPlotBucket[]
    /** Value formatter for the tooltip lines (seconds in, short label out). */
    formatSeconds: (seconds: number) => string
    /** Accessible name for the chart (role="img"); screen readers can't read the per-bucket titles. */
    ariaLabel?: string
    className?: string
}

// Unit grid (1 unit/bucket) stretched to the cell via preserveAspectRatio="none", like
// FailureSparkline — adapts to any window length without per-window sizing.
const VIEW_HEIGHT = 100
const BASELINE_Y = 96
const TOP_PAD = 6
// A degenerate box (all quantiles equal, e.g. one sample) still needs visible height.
const MIN_BOX_HEIGHT = 2
const BOX_INSET = 0.22 // gutter between boxes within each unit-wide bucket
const WHISKER_WIDTH = 0.05 // thin vertical rect; a stroked line would distort under the x stretch

/**
 * One box-and-whisker per bucket on a dotted baseline: whisker min→max, box p25→p75, a median
 * line, shared zero-based seconds scale across the window. Empty buckets stay empty slots so a
 * quiet stretch reads as "nothing deployed", not missing data.
 */
export function MergeToDeployBoxPlot({
    buckets,
    formatSeconds,
    ariaLabel = 'Merge to deploy distribution',
    className,
}: MergeToDeployBoxPlotProps): JSX.Element {
    const slots = Math.max(buckets.length, 1)
    const maxSeconds = Math.max(...buckets.map((bucket) => bucket.maxSeconds ?? 0), 1)
    const usableHeight = BASELINE_Y - TOP_PAD
    const yOf = (seconds: number): number => BASELINE_Y - (seconds / maxSeconds) * usableHeight

    return (
        <svg
            className={cn('h-40 w-full overflow-visible', className)}
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
                vectorEffect="non-scaling-stroke"
            />
            {buckets.map((bucket, i) => {
                const hasData =
                    bucket.count > 0 &&
                    bucket.minSeconds != null &&
                    bucket.p25Seconds != null &&
                    bucket.p50Seconds != null &&
                    bucket.p75Seconds != null &&
                    bucket.maxSeconds != null
                const title = hasData
                    ? [
                          bucket.label,
                          `${bucket.count} PR${bucket.count === 1 ? '' : 's'} deployed`,
                          `max ${formatSeconds(bucket.maxSeconds ?? 0)}`,
                          `p90 ${bucket.p90Seconds != null ? formatSeconds(bucket.p90Seconds) : '—'}`,
                          `p75 ${formatSeconds(bucket.p75Seconds ?? 0)}`,
                          `median ${formatSeconds(bucket.p50Seconds ?? 0)}`,
                          `p25 ${formatSeconds(bucket.p25Seconds ?? 0)}`,
                          `min ${formatSeconds(bucket.minSeconds ?? 0)}`,
                      ].join('\n')
                    : `${bucket.label}\nNothing deployed`
                if (!hasData) {
                    return (
                        <rect key={i} x={i} y={0} width={1} height={VIEW_HEIGHT} fill="transparent">
                            <title>{title}</title>
                        </rect>
                    )
                }
                const boxTop = yOf(bucket.p75Seconds ?? 0)
                const boxBottom = yOf(bucket.p25Seconds ?? 0)
                const boxHeight = Math.max(boxBottom - boxTop, MIN_BOX_HEIGHT)
                const boxX = i + BOX_INSET
                const boxWidth = 1 - BOX_INSET * 2
                const center = i + 0.5
                return (
                    <g key={i}>
                        <rect
                            x={center - WHISKER_WIDTH / 2}
                            y={yOf(bucket.maxSeconds ?? 0)}
                            width={WHISKER_WIDTH}
                            height={Math.max(yOf(bucket.minSeconds ?? 0) - yOf(bucket.maxSeconds ?? 0), 1)}
                            fill="var(--muted)"
                        />
                        <rect
                            x={boxX}
                            y={boxTop}
                            width={boxWidth}
                            height={boxHeight}
                            fill="var(--data-color-1)"
                            fillOpacity={0.45}
                        />
                        <rect
                            x={boxX}
                            y={yOf(bucket.p50Seconds ?? 0) - 0.75}
                            width={boxWidth}
                            height={1.5}
                            fill="var(--data-color-1)"
                        />
                        {/* Full-height transparent hit area so hovering anywhere in the bucket shows its tooltip. */}
                        <rect x={i} y={0} width={1} height={VIEW_HEIGHT} fill="transparent">
                            <title>{title}</title>
                        </rect>
                    </g>
                )
            })}
        </svg>
    )
}
