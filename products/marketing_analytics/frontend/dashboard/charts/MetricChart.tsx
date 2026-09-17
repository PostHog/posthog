import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'
import { Series, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'
import { displayBreakdownValue } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendResult } from '~/types'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { focusedSeries } from './seriesFocus'

const CHART_HEIGHT = 260

const formatValue = (value: number, format: string): string => {
    switch (format) {
        case 'percentage':
            return `${value.toFixed(1)}%`
        case 'duration':
            return humanFriendlyDuration(value) ?? String(value)
        case 'decimal':
            return value.toFixed(2)
        default:
            return humanFriendlyNumber(value)
    }
}

export function MetricChart(): JSX.Element | null {
    const { expandedMetric, expandedMetricSpec, metricChartQuery, chartMode, focusedBreakdownValue, breakdownLabel } =
        useValues(marketingDashboardLogic)
    const { setChartMode, setFocusedBreakdownValue } = useActions(marketingDashboardLogic)
    const theme = useChartTheme()

    if (!expandedMetric || !expandedMetricSpec || !metricChartQuery) {
        return null
    }

    // overflow-hidden clips the chart canvas to the rounded corners, which it otherwise squares off.
    return (
        <div className="border rounded overflow-hidden bg-surface-primary flex flex-col">
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <h3 className="m-0 text-base font-semibold">{expandedMetricSpec.label} over time</h3>
                <LemonSegmentedButton
                    size="xsmall"
                    value={chartMode}
                    onChange={(mode) => setChartMode(mode)}
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
            <ChartBody
                format={expandedMetricSpec.format}
                label={expandedMetricSpec.label}
                breakdownLabel={breakdownLabel}
                focused={focusedBreakdownValue}
                onFocus={setFocusedBreakdownValue}
                theme={theme}
            />
        </div>
    )
}

function ChartBody({
    format,
    label,
    breakdownLabel,
    focused,
    onFocus,
    theme,
}: {
    format: string
    label: string
    breakdownLabel: string
    focused: string | null
    onFocus: (value: string | null) => void
    theme: ReturnType<typeof useChartTheme>
}): JSX.Element {
    const { metricChartQuery, chartMode } = useValues(marketingDashboardLogic)
    const logic = dataNodeLogic({
        query: metricChartQuery!,
        key: 'marketing-dashboard-metric-chart',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)

    const results = (response as { results?: TrendResult[] } | undefined)?.results
    const { series, labels } = useMemo(() => {
        const rows = results ?? []
        return {
            labels: rows[0]?.days ?? [],
            series: rows.map((row, index): Series => {
                const name =
                    chartMode === 'breakdown'
                        ? displayBreakdownValue(String(row.breakdown_value ?? ''), breakdownLabel)
                        : label
                return {
                    key: name,
                    label: name,
                    data: row.data ?? [],
                    ...focusedSeries(focused, name, index, theme),
                }
            }),
        }
    }, [results, chartMode, breakdownLabel, label, focused, theme])

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            yAxis: { tickFormatter: (value: number) => formatValue(value, format) },
            legend: { show: chartMode === 'breakdown', interactive: true, position: 'bottom' },
            tooltip: { placement: 'cursor', sortedByValue: true },
        }),
        [format, chartMode]
    )

    if (responseError && !responseLoading) {
        return (
            <div className="p-3">
                <LemonBanner type="error">Couldn't load this chart. Change the metric and try again.</LemonBanner>
            </div>
        )
    }

    // The skeleton holds the chart's own height, so opening a card doesn't shunt the table down
    // and then back up once the data lands.
    if (responseLoading && !results?.length) {
        return (
            <div className="px-3 pb-3" style={{ height: CHART_HEIGHT }}>
                <LemonSkeleton className="h-full w-full" />
            </div>
        )
    }

    if (!series.length) {
        return <div className="px-3 pb-6 text-secondary text-sm">No data for this metric in the selected range.</div>
    }

    return (
        <div className="px-3 pb-3 relative">
            {/* The chart sizes itself from this box, so it needs a flex column with a real height
             * rather than a plain block, or the canvas collapses and only the legend renders. */}
            <div className="flex flex-col" style={{ height: CHART_HEIGHT }}>
                <TimeSeriesLineChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={config}
                    onPointClick={(clicked) => onFocus(String(clicked.series.key ?? '') || null)}
                />
            </div>
            {responseLoading && <div className="absolute inset-0 bg-primary/40" aria-hidden />}
        </div>
    )
}
