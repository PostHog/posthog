import { useMemo } from 'react'

import { BarChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'

import { flattenSeriesRows } from './metricsReduce'
import { thresholdColor } from './metricsThresholds'
import { formatMetricValue } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'

/** One horizontal bar per series, sorted descending, colored by threshold. Grafana's
 * "top N by value". Needs a groupBy to be meaningful; the picker gates on that. */
export function BarGaugePanel({ series, display, unit, fallbackName }: MetricsPanelProps): JSX.Element {
    const theme = useChartTheme()
    const reducer = resolveReducer(display)

    const rows = useMemo(
        () =>
            flattenSeriesRows(series, [reducer])
                .filter((row) => row.values[reducer] !== null)
                .sort((a, b) => (b.values[reducer] ?? 0) - (a.values[reducer] ?? 0)),
        [series, reducer]
    )

    const chartSeries = useMemo(
        () => [
            {
                key: 'value',
                label: fallbackName,
                data: rows.map((row) => row.values[reducer] ?? 0),
                color: getColorVar(FALLBACK_COLOR),
                // Per-bar threshold colors.
                bars: rows.map((row) => ({
                    color: getColorVar(thresholdColor(row.values[reducer], display.thresholds, FALLBACK_COLOR)),
                })),
            },
        ],
        [rows, reducer, fallbackName, display.thresholds]
    )
    const labels = useMemo(
        () =>
            rows.map(
                (row) =>
                    Object.entries(row.labels)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(', ') ||
                    row.metricName ||
                    fallbackName
            ),
        [rows, fallbackName]
    )

    if (rows.length === 0) {
        return <div className="flex h-full items-center justify-center text-secondary text-sm">No data</div>
    }

    return (
        <div className="relative flex h-full w-full min-h-0 flex-col">
            <BarChart
                series={chartSeries}
                labels={labels}
                theme={theme}
                tooltip={(ctx) => {
                    const row = rows[ctx.dataIndex]
                    if (!row) {
                        return null
                    }
                    return <span>{formatMetricValue(row.values[reducer] ?? 0, unit)}</span>
                }}
            />
        </div>
    )
}
