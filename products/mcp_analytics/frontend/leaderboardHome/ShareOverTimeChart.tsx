import { useCallback, useMemo } from 'react'

import {
    type ChartTheme,
    createTooltipDateFormatter,
    DefaultTooltip,
    type Series,
    type TimeInterval,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { Card, CardState } from '../dashboard/Card'
import { formatNumber } from '../dashboard/formatters'
import { type ShareSeries } from './leaderboardShares'
import { LoadErrorMessage } from './LoadErrorMessage'
import { NoDataMessage } from './NoDataMessage'

export function ShareOverTimeChart({
    title,
    labels,
    series,
    loading,
    failed,
    theme,
    timezone,
    interval,
    colorOf,
}: {
    title: string
    labels: string[]
    series: ShareSeries[]
    loading: boolean
    failed: boolean
    theme: ChartTheme
    timezone: string
    interval: TimeInterval
    colorOf: (label: string, index: number) => string | undefined
}): JSX.Element {
    const chartSeries = useMemo<Series[]>(
        () =>
            series.map((s, index) => ({
                key: s.label,
                label: s.label,
                color: colorOf(s.label, index),
                data: s.data,
                fill: { opacity: 0.85 },
            })),
        [series, colorOf]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            percentStackView: true,
            legend: { show: true },
            showAxisLines: true,
            showTickMarks: true,
            showCrosshair: true,
            showGrid: true,
            xAxis: { interval, timezone },
            tooltip: { placement: 'cursor' },
        }),
        [timezone, interval]
    )
    const labelFormatter = useMemo(
        () => createTooltipDateFormatter({ interval, timezone, allDays: labels }),
        [interval, timezone, labels]
    )
    // A custom tooltip, because the config's value formatter sees only the share, not the hovered
    // day, so it cannot look up the call count behind it.
    const renderTooltip = useCallback(
        (ctx: TooltipContext) => {
            const callsAt = (s: Series): number => s.data[ctx.dataIndex] ?? 0
            const totalCalls = ctx.seriesData.reduce((sum, entry) => sum + callsAt(entry.series), 0)
            return (
                <DefaultTooltip
                    {...ctx}
                    labelFormatter={labelFormatter}
                    valueFormatter={(fraction, entry) =>
                        `${formatPercentage(fraction * 100, { compact: true })} · ${formatCalls(callsAt(entry.series))}`
                    }
                    showTotal
                    totalFormatter={() => formatCalls(totalCalls)}
                />
            )
        },
        [labelFormatter]
    )

    return (
        <Card title={title} className="min-w-0">
            <CardState
                loading={loading}
                isEmpty={series.every((s) => s.data.every((value) => value === 0))}
                skeleton={<Skeleton className="min-h-[300px] flex-1" />}
                empty={failed ? <LoadErrorMessage /> : <NoDataMessage />}
            >
                <div className="flex min-h-[300px] flex-1 flex-col">
                    <TimeSeriesLineChart
                        series={chartSeries}
                        labels={labels}
                        config={config}
                        theme={theme}
                        tooltip={renderTooltip}
                    />
                </div>
            </CardState>
        </Card>
    )
}

function formatCalls(calls: number): string {
    return `${formatNumber(calls)} ${calls === 1 ? 'call' : 'calls'}`
}
