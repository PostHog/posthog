import clsx from 'clsx'

import type { ReportMetricChartType } from '../../utils/reportMetrics'

const STRIP_WIDTH = 72
const STRIP_HEIGHT = 18
const LINE_PADDING = 2

function linePoints(values: number[]): { x: number; y: number }[] {
    const minValue = Math.min(...values)
    const maxValue = Math.max(...values)
    const range = maxValue - minValue
    const step = STRIP_WIDTH / (values.length - 1)
    const innerHeight = STRIP_HEIGHT - LINE_PADDING * 2

    return values.map((value, index) => ({
        x: index * step,
        // A flat series sits mid-strip; the figure beside it carries the level.
        y: LINE_PADDING + (range === 0 ? innerHeight / 2 : innerHeight - ((value - minValue) / range) * innerHeight),
    }))
}

/**
 * Row-sized strip of a metric's trailing buckets. Bars for buckets that add up, a line for buckets that
 * are levels; `reportMetricChartType` decides which. The shared `Sparkline` chart sizes its width from
 * the bucket count and mounts a chart per row, which is too heavy and too wide for a list of fifty
 * rows, so this draws plain elements at a fixed width instead.
 */
export function ReportCardSparkline({ values, type }: { values: number[]; type: ReportMetricChartType }): JSX.Element {
    if (type === 'line') {
        const points = linePoints(values)
        const lastPoint = points[points.length - 1]

        return (
            <svg
                className="h-4.5 w-18 flex-none overflow-visible"
                viewBox={`0 0 ${STRIP_WIDTH} ${STRIP_HEIGHT}`}
                preserveAspectRatio="none"
                aria-hidden
                data-attr="report-card-impact-sparkline"
                data-chart-type="line"
            >
                {/* The stroke palette has no border-primary entry, so reference the same token the bars use. */}
                <polyline
                    className="stroke-[var(--color-border-primary)]"
                    fill="none"
                    strokeWidth={1.5}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                    points={points.map((point) => `${point.x},${point.y}`).join(' ')}
                />
                <circle className="fill-accent" cx={lastPoint.x} cy={lastPoint.y} r={2} />
            </svg>
        )
    }

    const maxValue = Math.max(...values, 1)

    return (
        <div
            className="flex h-4.5 w-18 flex-none items-end gap-0.5"
            aria-hidden
            data-attr="report-card-impact-sparkline"
            data-chart-type="bar"
        >
            {values.map((value, index) => (
                <div
                    key={index}
                    className={clsx(
                        'min-h-0.5 flex-1 rounded-[1px]',
                        index === values.length - 1 ? 'bg-accent' : 'bg-border-primary'
                    )}
                    style={{ height: `${Math.max(10, (value / maxValue) * 100)}%` }}
                />
            ))}
        </div>
    )
}
