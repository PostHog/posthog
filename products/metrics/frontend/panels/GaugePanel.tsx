import { useMemo } from 'react'

import { Gauge, resolveGaugeBounds } from '@posthog/quill-charts'
import type { GaugeThreshold } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { formatSeriesNames } from '../components/metricsSeries'
import { flattenSeriesRows } from './metricsReduce'
import { safeColorToken } from './metricsThresholds'
import { metricValuesFormatter } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'
const MAX_GAUGES = 12

interface GaugeCell {
    key: string
    name: string
    value: number | null
    formatValue: (value: number) => string
}

/** A single-series radial gauge: the reduced value drawn as an arc between a min and a max,
 * colored by threshold. Grouped queries render one gauge per series, capped. */
export function GaugePanel({ series, display, fallbackName }: MetricsPanelProps): JSX.Element {
    const theme = useChartTheme()
    const reducer = resolveReducer(display)
    const min = display.yAxis?.min ?? undefined
    const max = display.yAxis?.max ?? undefined
    const thresholds = useMemo<GaugeThreshold[]>(
        () =>
            (display.thresholds ?? []).map((step) => ({
                value: step.value,
                color: `var(--${safeColorToken(step.color, FALLBACK_COLOR)})`,
            })),
        [display.thresholds]
    )

    const cells = useMemo<GaugeCell[]>(() => {
        const names = formatSeriesNames(
            series.map((s) => ({ labels: s.labels, metric_name: s.metricName ?? undefined, clause: s.clause })),
            fallbackName
        )
        const seen = new Map<string, number>()
        return (
            flattenSeriesRows(series, [reducer])
                .map((row, index) => ({ row, index }))
                // A series with no non-null point has nothing to draw; drop it like the other
                // scalar panels rather than render a dash gauge.
                .filter(({ row }) => row.values[reducer] !== null)
                .slice(0, MAX_GAUGES)
                .map(({ row, index }) => {
                    const value = row.values[reducer] ?? null
                    const bounds = resolveGaugeBounds({ value, min, max, thresholds })
                    // Two clauses can return the same metric and labels, so the clause is part of the
                    // identity, and a counter keeps any remaining collision unique.
                    const identity = `${series[index].clause ?? ''}|${row.metricName ?? ''}|${names[index]}`
                    const repeat = seen.get(identity) ?? 0
                    seen.set(identity, repeat + 1)
                    return {
                        key: repeat ? `${identity}#${repeat}` : identity,
                        name: names[index],
                        value,
                        formatValue: metricValuesFormatter(row.series.unit ?? undefined, [
                            value ?? 0,
                            bounds.min,
                            bounds.max,
                        ]),
                    }
                })
        )
    }, [series, reducer, fallbackName, min, max, thresholds])

    if (cells.length === 0) {
        return <div className="flex h-full items-center justify-center text-secondary text-sm">No data</div>
    }

    return (
        // Each cell needs a real height for the gauge to fill, and 140px keeps a gauge readable.
        <div className="grid h-full w-full auto-rows-[minmax(120px,1fr)] grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2 overflow-auto p-2">
            {cells.map((cell) => (
                <div key={cell.key} className="flex min-h-0 min-w-0 flex-col">
                    <Gauge
                        value={cell.value}
                        min={min}
                        max={max}
                        thresholds={thresholds}
                        color={`var(--${FALLBACK_COLOR})`}
                        theme={theme}
                        label={cell.name}
                        config={{ valueFormatter: cell.formatValue }}
                        dataAttr="metrics-gauge"
                    />
                </div>
            ))}
        </div>
    )
}
