import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    ChartLegend,
    type ChartTheme,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    legendItemsFromSeries,
} from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { Card, CardState } from '../dashboard/Card'
import { formatMsAsSeconds } from '../dashboard/formatters'
import { type DailyChartData } from '../mcpAnalyticsToolQualityLogic'

function buildConfig(timezone: string, yAxis?: TimeSeriesLineChartConfig['yAxis']): TimeSeriesLineChartConfig {
    return {
        yAxis: { showGrid: true, ...yAxis },
        showAxisLines: true,
        xAxis: { interval: 'day', timezone },
        showCrosshair: true,
        tooltip: { placement: 'cursor' },
    }
}

function ChartCard({
    title,
    loading,
    isEmpty,
    children,
}: {
    title: string
    loading: boolean
    isEmpty: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <Card title={title}>
            <CardState
                loading={loading}
                isEmpty={isEmpty}
                skeleton={<LemonSkeleton className="min-h-[220px] flex-1" />}
                empty={
                    <div className="flex min-h-[220px] flex-1 items-center justify-center text-center text-[12px] text-secondary">
                        No tool calls for this selection.
                    </div>
                }
            >
                {/* Dim while refreshing so date/tool changes give visible feedback. */}
                <div className={`flex min-h-[220px] flex-1 flex-col transition-opacity ${loading ? 'opacity-50' : ''}`}>
                    {children}
                </div>
            </CardState>
        </Card>
    )
}

export function ToolQualityCharts({
    data,
    loading,
    theme,
    timezone,
}: {
    data: DailyChartData
    loading: boolean
    theme: ChartTheme
    timezone: string
}): JSX.Element {
    const isEmpty = data.labels.length === 0

    const callsSeries = useMemo<Series[]>(
        () => [
            { key: 'calls', label: 'Calls', color: theme.colors[0], data: data.calls },
            { key: 'errors', label: 'Errors', color: theme.colors[4], data: data.errors },
        ],
        [data, theme]
    )
    const successSeries = useMemo<Series[]>(
        () => [{ key: 'successRate', label: 'Success rate', color: theme.colors[2], data: data.successRate }],
        [data, theme]
    )
    const latencySeries = useMemo<Series[]>(
        () => [
            { key: 'p50', label: 'p50', color: theme.colors[1], data: data.p50 },
            { key: 'p95', label: 'p95', color: theme.colors[0], data: data.p95 },
            { key: 'p99', label: 'p99', color: theme.colors[4], data: data.p99 },
        ],
        [data, theme]
    )

    const countsConfig = useChartConfig(() => buildConfig(timezone), [timezone])
    const percentConfig = useChartConfig(
        () => buildConfig(timezone, { tickFormatter: (value: number) => formatPercentage(value, { compact: true }) }),
        [timezone]
    )
    const latencyConfig = useChartConfig(() => buildConfig(timezone, { tickFormatter: formatMsAsSeconds }), [timezone])

    return (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <ChartCard title="Calls and errors" loading={loading} isEmpty={isEmpty}>
                <TimeSeriesLineChart
                    series={callsSeries}
                    labels={data.labels}
                    config={countsConfig}
                    theme={theme}
                    dataAttr="mcp-tool-quality-calls-chart"
                />
            </ChartCard>
            <ChartCard title="Success rate" loading={loading} isEmpty={isEmpty}>
                <TimeSeriesLineChart
                    series={successSeries}
                    labels={data.labels}
                    config={percentConfig}
                    theme={theme}
                    dataAttr="mcp-tool-quality-success-rate-chart"
                />
            </ChartCard>
            <ChartCard title="Latency (p50 / p95 / p99)" loading={loading} isEmpty={isEmpty}>
                <ChartLegend items={legendItemsFromSeries(latencySeries, theme)} position="top" align="end">
                    <TimeSeriesLineChart
                        series={latencySeries}
                        labels={data.labels}
                        config={latencyConfig}
                        theme={theme}
                        dataAttr="mcp-tool-quality-latency-chart"
                    />
                </ChartLegend>
            </ChartCard>
        </div>
    )
}
