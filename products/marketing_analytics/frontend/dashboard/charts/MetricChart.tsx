import { ReactNode, useMemo } from 'react'

import { LemonButton, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'
import { Series, TimeSeriesLineChart, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { focusedSeries } from './seriesFocus'

export interface MetricChartProps {
    label: string
    breakdownLabel: string
    format: 'number' | 'percentage' | 'duration' | 'decimal'
    timezone: string
    labels: string[]
    series: (Series & { key: string })[]
    chartMode: 'total' | 'breakdown'
    focusedBreakdownValue: string | null
    loading: boolean
    error: ReactNode
    onChartModeChange: (mode: 'total' | 'breakdown') => void
    onFocus: (value: string | null) => void
}

export function MetricChart({
    label,
    breakdownLabel,
    format,
    timezone,
    labels,
    series,
    chartMode,
    focusedBreakdownValue,
    loading,
    error,
    onChartModeChange,
    onFocus,
}: MetricChartProps): JSX.Element {
    const theme = useChartTheme()
    const focused =
        chartMode === 'breakdown' && series.some((row) => row.key === focusedBreakdownValue)
            ? focusedBreakdownValue
            : null
    const chartSeries = useMemo(
        () =>
            series.map((row, index) => ({
                ...row,
                // Chart hit-testing needs a nonempty key; selection keeps the raw breakdown value.
                key: JSON.stringify(row.key),
                ...focusedSeries(focused, row.key, index, theme),
            })),
        [series, focused, theme]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(() => {
        const formatValue = (value: number): string => {
            switch (format) {
                case 'percentage':
                    return `${(value * 100).toFixed(1)}%`
                case 'duration':
                    return humanFriendlyDuration(value) ?? String(value)
                case 'decimal':
                    return value.toFixed(2)
                default:
                    return humanFriendlyNumber(value)
            }
        }
        return {
            xAxis: { timezone },
            yAxis: { tickFormatter: formatValue },
            legend: { show: chartMode === 'breakdown', interactive: true, position: 'bottom' },
            tooltip: {
                placement: 'cursor',
                sortedByValue: true,
                valueFormatter: formatValue,
                pinnable: chartMode === 'breakdown',
                resolveClickToNearestSeries: true,
            },
        }
    }, [format, chartMode, timezone])
    const hasData = series.some((row) => row.data.some(Number.isFinite)) && labels.length > 0

    // Keep the canvas inside the rounded panel without changing its measured height.
    return (
        <div className="border rounded overflow-hidden bg-surface-primary flex flex-col" aria-busy={loading}>
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <h3 className="m-0 text-base font-semibold break-words min-w-0">{`${label} over time`}</h3>
                <div className="flex flex-wrap items-center gap-2">
                    {focused !== null && (
                        <LemonButton
                            size="xsmall"
                            onClick={() => onFocus(null)}
                            disabledReason={loading ? 'Wait for the chart to finish loading' : undefined}
                            data-attr="marketing-dashboard-chart-clear-focus"
                        >
                            Clear selection
                        </LemonButton>
                    )}
                    <LemonSegmentedButton
                        size="xsmall"
                        value={chartMode}
                        onChange={onChartModeChange}
                        disabledReason={loading ? 'Wait for the chart to finish loading' : undefined}
                        options={[
                            {
                                value: 'breakdown',
                                label: `By ${breakdownLabel.toLowerCase()}`,
                                'data-attr': 'marketing-dashboard-chart-mode-breakdown',
                            },
                            { value: 'total', label: 'Total', 'data-attr': 'marketing-dashboard-chart-mode-total' },
                        ]}
                    />
                </div>
            </div>
            {loading && !hasData ? (
                <div className="h-64 px-3 pb-3" aria-label="Loading chart">
                    <LemonSkeleton className="h-full w-full" />
                </div>
            ) : error && !loading ? (
                <div className="p-3">{error}</div>
            ) : !hasData ? (
                <div className="px-3 pb-6 text-secondary text-sm">
                    No data for this metric. Try another date range or change your filters.
                </div>
            ) : (
                <div className="px-3 pb-3 relative">
                    {/* The canvas needs a flex column with a real height or only the legend renders. */}
                    <div className="flex flex-col h-64">
                        <TimeSeriesLineChart
                            key={chartMode}
                            series={chartSeries}
                            labels={labels}
                            theme={theme}
                            config={config}
                            dataAttr="marketing-dashboard-metric-chart"
                            onPointClick={
                                chartMode === 'breakdown' && !loading
                                    ? ({ series: clicked }) =>
                                          onFocus(
                                              series.find((row) => JSON.stringify(row.key) === clicked.key)?.key ?? null
                                          )
                                    : undefined
                            }
                        />
                    </div>
                    {loading && <div className="absolute inset-0 bg-primary/40" aria-hidden />}
                </div>
            )}
        </div>
    )
}
