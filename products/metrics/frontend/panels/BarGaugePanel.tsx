import { useMemo } from 'react'

import { BarChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'

import { seriesLabelText } from '../components/metricsSeries'
import { flattenSeriesRows } from './metricsReduce'
import { thresholdColor } from './metricsThresholds'
import { metricValuesFormatter } from './metricsUnits'
import type { MetricsPanelProps } from './registry'
import { resolveReducer } from './registry'

const FALLBACK_COLOR = 'data-color-1'

/** One horizontal bar per series, sorted descending, colored by threshold. Grafana's
 * "top N by value". Needs a groupBy to be meaningful; the picker gates on that. */
export function BarGaugePanel({ series, display, fallbackName }: MetricsPanelProps): JSX.Element {
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
                    color: getColorVar(thresholdColor(row.values[reducer] ?? null, display.thresholds, FALLBACK_COLOR)),
                })),
            },
        ],
        [rows, reducer, fallbackName, display.thresholds]
    )
    // Bars run sideways so every series gets a readable label on its own row. A tile has a fixed
    // height, so rows that do not fit are dropped from the bottom of the ranking instead of growing it.
    const config = useMemo(
        () => ({
            axisOrientation: 'horizontal' as const,
            bars: { fitToHeight: true, valueDomain: { min: display.yAxis?.min, max: display.yAxis?.max } },
        }),
        [display.yAxis?.min, display.yAxis?.max]
    )
    // `MetricsPanel` gives every series the same resolved unit, so the first row speaks for the chart.
    const formatValue = useMemo(
        () =>
            metricValuesFormatter(
                rows[0]?.series.unit ?? undefined,
                rows.map((row) => row.values[reducer] ?? 0)
            ),
        [rows, reducer]
    )
    const labels = useMemo(
        () => rows.map((row) => seriesLabelText(row.labels, display.legendFormat) || row.metricName || fallbackName),
        [rows, fallbackName, display.legendFormat]
    )

    if (rows.length === 0) {
        return <div className="flex h-full items-center justify-center text-secondary text-sm">No data</div>
    }

    return (
        <div className="relative flex h-full w-full min-h-0 flex-col">
            <BarChart
                series={chartSeries}
                labels={labels}
                config={config}
                theme={theme}
                tooltip={(ctx) => {
                    const row = rows[ctx.dataIndex]
                    if (!row) {
                        return null
                    }
                    return <span>{formatValue(row.values[reducer] ?? 0)}</span>
                }}
            />
        </div>
    )
}
