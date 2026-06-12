import { useCallback, useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    ChartLegend,
    type ChartTheme,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
    legendItemsFromSeries,
} from '@posthog/quill-charts'

import { formatPercentage } from 'lib/utils'

import { Card, CardState } from '../dashboard/Card'
import { ChartTooltip } from '../dashboard/ChartTooltip'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { type DailyChartData } from '../mcpAnalyticsToolQualityLogic'

function buildConfig(timezone: string, yAxis?: TimeSeriesLineChartConfig['yAxis']): TimeSeriesLineChartConfig {
    return {
        yAxis: { showGrid: false, ...yAxis },
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
                <div className="flex min-h-[220px] flex-1 flex-col">{children}</div>
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

    const countsConfig = useMemo(() => buildConfig(timezone), [timezone])
    const percentConfig = useMemo(
        () => buildConfig(timezone, { tickFormatter: (value: number) => formatPercentage(value, { compact: true }) }),
        [timezone]
    )
    const latencyConfig = useMemo(
        () => buildConfig(timezone, { tickFormatter: (value: number) => (value === 0 ? '0' : formatMs(value)) }),
        [timezone]
    )

    const callsTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <ChartTooltip
                title={ctx.label}
                rows={[
                    ['Calls', formatNumber(data.calls[ctx.dataIndex] ?? 0)],
                    ['Errors', formatNumber(data.errors[ctx.dataIndex] ?? 0)],
                ]}
            />
        ),
        [data]
    )
    const successTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <ChartTooltip
                title={ctx.label}
                rows={[
                    ['Success rate', formatPercentage(data.successRate[ctx.dataIndex] ?? 0, { compact: true })],
                    ['Calls', formatNumber(data.calls[ctx.dataIndex] ?? 0)],
                    ['Errors', formatNumber(data.errors[ctx.dataIndex] ?? 0)],
                ]}
            />
        ),
        [data]
    )
    const latencyTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <ChartTooltip
                title={ctx.label}
                rows={[
                    ['p50', formatMs(data.p50[ctx.dataIndex] ?? 0)],
                    ['p95', formatMs(data.p95[ctx.dataIndex] ?? 0)],
                    ['p99', formatMs(data.p99[ctx.dataIndex] ?? 0)],
                ]}
            />
        ),
        [data]
    )

    return (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <ChartCard title="Calls and errors" loading={loading} isEmpty={isEmpty}>
                <TimeSeriesLineChart
                    series={callsSeries}
                    labels={data.labels}
                    config={countsConfig}
                    theme={theme}
                    tooltip={callsTooltip}
                    dataAttr="mcp-tool-quality-calls-chart"
                />
            </ChartCard>
            <ChartCard title="Success rate" loading={loading} isEmpty={isEmpty}>
                <TimeSeriesLineChart
                    series={successSeries}
                    labels={data.labels}
                    config={percentConfig}
                    theme={theme}
                    tooltip={successTooltip}
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
                        tooltip={latencyTooltip}
                        dataAttr="mcp-tool-quality-latency-chart"
                    />
                </ChartLegend>
            </ChartCard>
        </div>
    )
}
