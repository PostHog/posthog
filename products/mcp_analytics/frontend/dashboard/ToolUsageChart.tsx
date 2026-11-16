import { useMemo } from 'react'

import {
    type ChartTheme,
    type Series,
    type TimeInterval,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
} from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'

import { type ToolDailySeries } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartSkeleton } from './ChartSkeleton'

export function ToolUsageChart({
    data,
    loading,
    failed,
    onRetry,
    theme,
    timezone,
    interval,
}: {
    data: ToolDailySeries
    loading: boolean
    failed?: boolean
    onRetry?: () => void
    theme: ChartTheme
    timezone: string
    interval: TimeInterval
}): JSX.Element {
    const series = useMemo<Series[]>(
        () =>
            data.tools.map((t, i) => ({
                key: t.tool,
                label: t.tool,
                color: theme.colors[i % theme.colors.length],
                data: t.data,
            })),
        [data, theme]
    )
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: 'stacked',
            barCornerRadius: 4,
            showAxisLines: true,
            showTickMarks: true,
            showCrosshair: true,
            showGrid: true,
            xAxis: { interval, timezone },
            tooltip: { placement: 'cursor' },
        }),
        [timezone, interval]
    )

    return (
        <Card title="Tool call breakdown">
            <CardState
                loading={loading}
                // Rows whose buckets fall outside the client's keys still contribute their tool
                // names, so `tools` can be non-empty with every series zeroed. Checking the counts
                // rather than the names keeps that rendering as the empty state, not a blank stack.
                isEmpty={data.tools.every((t) => t.data.every((v) => v === 0))}
                failed={failed}
                onRetry={onRetry}
                className="min-h-[300px]"
                skeleton={<ChartSkeleton kind="columns" />}
                empty={
                    <div className="flex flex-1 items-center justify-center py-6 text-center text-[12px] text-secondary">
                        No tool calls in this date range. Try a wider range.
                    </div>
                }
            >
                <TimeSeriesBarChart series={series} labels={data.labels} config={config} theme={theme} />
            </CardState>
        </Card>
    )
}
