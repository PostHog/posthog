import { useMemo } from 'react'

import { Gauge, resolveGaugeBounds } from '@posthog/quill-charts'
import type { GaugeThreshold } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { flattenSeriesRows } from './metricsReduce'
import { safeColorToken } from './metricsThresholds'
import { metricValuesFormatter } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'
const MAX_GAUGES = 12

/** A single-series radial gauge: the reduced value drawn as an arc between a min and a max,
 * colored by threshold. Grouped queries render one gauge per series, capped. */
export function GaugePanel({ series, display, fallbackName }: MetricsPanelProps): JSX.Element {
    const theme = useChartTheme()
    const reducer = resolveReducer(display)
    // A series with no non-null point has nothing to draw; drop it like the other
    // scalar panels rather than render a dash gauge.
    const rows = useMemo(
        () =>
            flattenSeriesRows(series, [reducer])
                .filter((row) => row.values[reducer] !== null)
                .slice(0, MAX_GAUGES),
        [series, reducer]
    )
    const thresholds = useMemo<GaugeThreshold[]>(
        () =>
            (display.thresholds ?? []).map((step) => ({
                value: step.value,
                color: `var(--${safeColorToken(step.color, FALLBACK_COLOR)})`,
            })),
        [display.thresholds]
    )

    if (rows.length === 0) {
        return <div className="flex h-full items-center justify-center text-secondary text-sm">No data</div>
    }

    const min = display.yAxis?.min ?? undefined
    const max = display.yAxis?.max ?? undefined
    return (
        // Each cell needs a real height for the gauge to fill, and 140px keeps a gauge readable.
        <div className="grid h-full w-full auto-rows-[minmax(120px,1fr)] grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2 overflow-auto p-2">
            {rows.map((row) => {
                const value = row.values[reducer] ?? null
                const bounds = resolveGaugeBounds({ value, min, max, thresholds })
                const name =
                    Object.entries(row.labels)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(', ') ||
                    row.metricName ||
                    fallbackName
                return (
                    <div key={`${row.metricName ?? ''}|${name}`} className="flex min-h-0 min-w-0 flex-col">
                        <Gauge
                            value={value}
                            min={min}
                            max={max}
                            thresholds={thresholds}
                            color={`var(--${FALLBACK_COLOR})`}
                            theme={theme}
                            label={name}
                            valueFormatter={metricValuesFormatter(row.series.unit ?? undefined, [
                                value ?? 0,
                                bounds.min,
                                bounds.max,
                            ])}
                            dataAttr="metrics-gauge"
                        />
                    </div>
                )
            })}
        </div>
    )
}
