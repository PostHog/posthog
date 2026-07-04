import { useMemo } from 'react'

import {
    type ChartTheme,
    type Series,
    type TimeInterval,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { useChartConfig } from 'lib/charts/hooks'

import { type ToolDailySeries } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'

export function ToolUsageChart({
    data,
    loading,
    theme,
    timezone,
    interval,
}: {
    data: ToolDailySeries
    loading: boolean
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
            yAxis: { showGrid: true },
            showAxisLines: true,
            xAxis: { interval, timezone },
            tooltip: { placement: 'cursor' },
        }),
        [timezone, interval]
    )

    return (
        <Card title="Tool call breakdown">
            <CardState
                loading={loading}
                isEmpty={data.tools.length === 0}
                skeleton={<Skeleton className="h-[260px] w-full" />}
                empty={<div className="py-6 text-center text-[12px] text-secondary">No tool calls yet.</div>}
            >
                <div className="flex h-[260px] flex-col">
                    <TimeSeriesBarChart series={series} labels={data.labels} config={config} theme={theme} />
                </div>
            </CardState>
        </Card>
    )
}
