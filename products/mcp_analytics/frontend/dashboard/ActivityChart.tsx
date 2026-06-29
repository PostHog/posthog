import { useMemo } from 'react'

import {
    type ChartTheme,
    type Series,
    type TimeInterval,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { type DailyActivity } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'

export function ActivityChart({
    daily,
    loading,
    theme,
    timezone,
    interval,
    incompleteTail,
}: {
    daily: DailyActivity
    loading: boolean
    theme: ChartTheme
    timezone: string
    interval: TimeInterval
    // When true, the final bucket is the current in-progress interval — dash that segment so the
    // partial period reads as "not finished yet" rather than a drop in tool calls.
    incompleteTail?: boolean
}): JSX.Element {
    const series = useMemo<Series[]>(() => {
        const totals = daily.successes.map((s, i) => s + (daily.errors[i] ?? 0))
        // `incompleteTail` is only true when the window has ≥2 buckets (lastBucketIsInProgress owns
        // that rule), and `daily` is zero-filled to the bucket count — so the final segment exists.
        // The renderer also clamps fromIndex, so a stray single-point series can't go out of range.
        const partialStroke = incompleteTail ? { partial: { fromIndex: totals.length - 1 } } : undefined
        return [
            { key: 'calls', label: 'Tool calls', color: theme.colors[0], data: totals, stroke: partialStroke },
            { key: 'errors', label: 'Errors', color: theme.colors[4], data: daily.errors, stroke: partialStroke },
        ]
    }, [daily, theme, incompleteTail])
    // quill's built-in date tick formatter only kicks in when both interval and timezone are set.
    const config = useMemo<TimeSeriesLineChartConfig>(
        () => ({
            yAxis: { showGrid: false },
            showAxisLines: true,
            xAxis: { interval, timezone },
            showCrosshair: true,
            tooltip: { placement: 'cursor' },
        }),
        [timezone, interval]
    )

    return (
        <Card className="flex flex-1 flex-col" title="Tool calls and errors">
            <CardState
                loading={loading}
                isEmpty={daily.successes.every((v) => v === 0) && daily.errors.every((v) => v === 0)}
                skeleton={<Skeleton className="min-h-[300px] flex-1" />}
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
