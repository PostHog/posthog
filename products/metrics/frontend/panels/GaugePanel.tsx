import { getColorVar } from 'lib/colors'

import { flattenSeriesRows } from './metricsReduce'
import { thresholdColor } from './metricsThresholds'
import { formatMetricValue } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'

/** The arc spans 240 degrees (a typical gauge sweep), from -210° to 30°. */
const ARC_START_DEG = -210
const ARC_SWEEP_DEG = 240

function polarToCartesian(cx: number, cy: number, r: number, deg: number): [number, number] {
    const rad = (deg * Math.PI) / 180
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
}

function arcPath(cx: number, cy: number, r: number, fromDeg: number, toDeg: number): string {
    const [x0, y0] = polarToCartesian(cx, cy, r, fromDeg)
    const [x1, y1] = polarToCartesian(cx, cy, r, toDeg)
    const largeArc = toDeg - fromDeg > 180 ? 1 : 0
    return `M ${x0} ${y0} A ${r} ${r} 0 ${largeArc} 1 ${x1} ${y1}`
}

/** Bounds for the arc: explicit yAxis min/max first, else the threshold extremes, else 0..value. */
function gaugeBounds(value: number, display: MetricsPanelProps['display']): { min: number; max: number } {
    const min = display.yAxis?.min ?? display.thresholds?.[0]?.value ?? 0
    const max =
        display.yAxis?.max ??
        (display.thresholds?.length ? Math.max(...display.thresholds.map((t) => t.value)) : undefined) ??
        Math.max(value, min + 1)
    return max > min ? { min, max } : { min, max: min + 1 }
}

/** A single-series radial gauge: the reduced value drawn as an arc between a min and a max,
 * colored by threshold. Grouped queries render one gauge per series, capped. */
export function GaugePanel({ series, display, unit, fallbackName }: MetricsPanelProps): JSX.Element {
    const reducer = resolveReducer(display)
    const rows = flattenSeriesRows(series, [reducer]).slice(0, 12)

    if (rows.length === 0) {
        return <div className="flex h-full items-center justify-center text-secondary text-sm">No data</div>
    }

    return (
        <div className="flex h-full w-full flex-wrap content-center items-center justify-center gap-4 overflow-auto p-2">
            {rows.map((row, index) => {
                const value = row.values[reducer]
                const { min, max } = gaugeBounds(value ?? 0, display)
                const fraction = value === null ? 0 : Math.min(Math.max((value - min) / (max - min), 0), 1)
                const color = getColorVar(thresholdColor(value, display.thresholds, FALLBACK_COLOR))
                const name =
                    Object.entries(row.labels)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(', ') ||
                    row.metricName ||
                    fallbackName

                const cx = 60
                const cy = 60
                const r = 48
                return (
                    <div key={index} className="flex flex-col items-center" title={name}>
                        <svg width="120" height="100" viewBox="0 0 120 100" role="img" aria-label={`${name} gauge`}>
                            {/* track */}
                            <path
                                d={arcPath(cx, cy, r, ARC_START_DEG, ARC_START_DEG + ARC_SWEEP_DEG)}
                                fill="none"
                                stroke="var(--color-graph-axis-line)"
                                strokeWidth="10"
                                strokeLinecap="round"
                            />
                            {/* value */}
                            {fraction > 0 && (
                                <path
                                    d={arcPath(cx, cy, r, ARC_START_DEG, ARC_START_DEG + ARC_SWEEP_DEG * fraction)}
                                    fill="none"
                                    stroke={color}
                                    strokeWidth="10"
                                    strokeLinecap="round"
                                />
                            )}
                            <text
                                x={cx}
                                y={cy + 4}
                                textAnchor="middle"
                                fontSize="16"
                                fontWeight="600"
                                fill="currentColor"
                            >
                                {value === null ? '—' : formatMetricValue(value, unit)}
                            </text>
                            <text
                                x={cx}
                                y={cy + 22}
                                textAnchor="middle"
                                fontSize="9"
                                fill="var(--color-graph-axis-label)"
                            >
                                {formatMetricValue(min, unit)} – {formatMetricValue(max, unit)}
                            </text>
                        </svg>
                        <span className="text-xs text-secondary max-w-[120px] truncate">{name}</span>
                    </div>
                )
            })}
        </div>
    )
}
