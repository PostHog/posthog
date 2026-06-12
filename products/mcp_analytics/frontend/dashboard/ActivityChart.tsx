import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    type ChartTheme,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { type DailyActivity } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'

export function ActivityChart({
    daily,
    loading,
    theme,
    timezone,
}: {
    daily: DailyActivity
    loading: boolean
    theme: ChartTheme
    timezone: string
}): JSX.Element {
    const series = useMemo<Series[]>(() => {
        const totals = daily.successes.map((s, i) => s + (daily.errors[i] ?? 0))
        return [
            { key: 'calls', label: 'Tool calls', color: theme.colors[0], data: totals },
            { key: 'errors', label: 'Errors', color: theme.colors[4], data: daily.errors },
        ]
    }, [daily, theme])
    // quill's built-in date tick formatter only kicks in when both interval and timezone are set.
    const config = useMemo<TimeSeriesLineChartConfig>(
        () => ({
            yAxis: { showGrid: false },
            showAxisLines: true,
            xAxis: { interval: 'day', timezone },
            showCrosshair: true,
            tooltip: { placement: 'cursor' },
        }),
        [timezone]
    )

    return (
        <Card className="flex flex-1 flex-col" title="Daily tool calls and errors">
            <CardState
                loading={loading}
                isEmpty={daily.labels.length === 0}
                skeleton={<LemonSkeleton className="min-h-[300px] flex-1" />}
                empty={
                    <div className="flex flex-1 items-center justify-center py-6 text-center text-[12px] text-secondary">
                        No activity yet.
                    </div>
                }
            >
                <div className="flex min-h-[300px] flex-1 flex-col">
                    <TimeSeriesLineChart series={series} labels={daily.labels} config={config} theme={theme} />
                </div>
            </CardState>
        </Card>
    )
}
