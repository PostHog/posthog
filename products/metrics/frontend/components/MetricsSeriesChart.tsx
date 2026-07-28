import { useCallback, useMemo } from 'react'

import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'

import { MetricsChartLegend } from './MetricsChartLegend'
import { formatSeriesName, seriesColor } from './metricsSeries'

/** Source-agnostic series shape: the REST viewer (`_MetricSeriesApi`) and the
 * `MetricsQuery` schema node (`MetricsQuerySeries`) both map onto it. */
export interface MetricsChartSeries {
    labels: Record<string, string>
    points: { time: string; value: number }[]
    metricName?: string | null
}

/** Multi-series metric line chart + legend, shared by the Viewer and the
 * dashboard/insight tile. Every series shares one time grid (the backend
 * zero-fills), so the x-axis comes from the first series. */
export function MetricsSeriesChart({
    series,
    fallbackName,
    className,
}: {
    series: MetricsChartSeries[]
    fallbackName: string
    className?: string
}): JSX.Element {
    const chartSeries = useMemo(
        () =>
            series.map((s, index) => ({
                name: formatSeriesName({ labels: s.labels, metric_name: s.metricName ?? undefined }, fallbackName),
                values: s.points.map((p) => p.value),
                color: seriesColor(index),
            })),
        [series, fallbackName]
    )
    const sparklineLabels = useMemo(() => (series[0]?.points ?? []).map((p) => p.time), [series])

    // Mirrors the format/timeUnit ladder LogsSparkline uses so the X-axis density
    // matches the selected range.
    const { timeUnit, tickFormat } = useMemo(() => {
        if (!sparklineLabels.length) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm' }
        }
        const first = dayjs(sparklineLabels[0])
        const last = dayjs(sparklineLabels[sparklineLabels.length - 1])
        const hoursDiff = last.diff(first, 'hours')
        if (hoursDiff <= 1) {
            return { timeUnit: 'second' as const, tickFormat: 'HH:mm:ss' }
        }
        if (hoursDiff <= 6) {
            return { timeUnit: 'minute' as const, tickFormat: 'HH:mm:ss' }
        }
        if (hoursDiff <= 48) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm' }
        }
        return { timeUnit: 'day' as const, tickFormat: 'D MMM HH:mm' }
    }, [sparklineLabels])

    const withXScale = useCallback(
        (scale: AnyScaleOptions): AnyScaleOptions =>
            ({
                ...scale,
                type: 'timeseries',
                ticks: {
                    display: true,
                    maxRotation: 0,
                    maxTicksLimit: 6,
                    font: { size: 10, lineHeight: 1 },
                    callback: function (value: string | number) {
                        return dayjs(value).format(tickFormat)
                    },
                },
                time: { unit: timeUnit },
            }) as AnyScaleOptions,
        [timeUnit, tickFormat]
    )

    const renderLabel = useCallback((label: string): string => dayjs(label).format('D MMM YYYY HH:mm:ss'), [])

    return (
        <div className={className}>
            <div className="flex-1 min-h-0">
                <Sparkline
                    type="line"
                    data={chartSeries}
                    labels={sparklineLabels}
                    className="w-full h-full"
                    withXScale={withXScale}
                    renderLabel={renderLabel}
                />
            </div>
            <MetricsChartLegend series={chartSeries} />
        </div>
    )
}
