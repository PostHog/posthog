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
import { formatPercentage } from 'lib/utils/numbers'

import { Card, CardState } from '../dashboard/Card'
import { type ShareSeries } from './leaderboardShares'
import { NoDataMessage } from './NoDataMessage'

export function ShareOverTimeChart({
    title,
    labels,
    series,
    loading,
    theme,
    timezone,
    interval,
    colorOf,
}: {
    title: string
    labels: string[]
    series: ShareSeries[]
    loading: boolean
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
            })),
        [series, colorOf]
    )
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: 'percent',
            legend: { show: true },
            barCornerRadius: 4,
            showAxisLines: true,
            showTickMarks: true,
            showCrosshair: true,
            showGrid: true,
            xAxis: { interval, timezone },
            tooltip: {
                placement: 'cursor',
                valueFormatter: (fraction) => formatPercentage(fraction * 100, { compact: true }),
            },
        }),
        [timezone, interval]
    )

    return (
        <Card title={title} className="min-w-0">
            <CardState
                loading={loading}
                isEmpty={series.every((s) => s.data.every((value) => value === 0))}
                skeleton={<Skeleton className="min-h-[300px] flex-1" />}
                empty={<NoDataMessage />}
            >
                <div className="flex min-h-[300px] flex-1 flex-col">
                    <TimeSeriesBarChart series={chartSeries} labels={labels} config={config} theme={theme} />
                </div>
            </CardState>
        </Card>
    )
}
