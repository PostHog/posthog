import { useMemo } from 'react'

import {
    type ChartTheme,
    type Series,
    type TimeInterval,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { useChartConfig } from 'lib/charts/hooks'

import { Card, CardState } from '../dashboard/Card'
import { NoDataMessage } from './NoDataMessage'

export interface TrendLine {
    key: string
    label: string
    data: number[]
}

export function TrendLineCard({
    title,
    labels,
    lines,
    loading,
    isEmpty,
    theme,
    timezone,
    interval,
    formatTick,
}: {
    title: string
    labels: string[]
    lines: TrendLine[]
    loading: boolean
    isEmpty: boolean
    theme: ChartTheme
    timezone: string
    interval: TimeInterval
    formatTick: (value: number) => string
}): JSX.Element {
    const series = useMemo<Series[]>(
        () => lines.map((line, index) => ({ ...line, color: theme.colors[index % theme.colors.length] })),
        [lines, theme]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            curve: 'monotone',
            legend: { show: true },
            showAxisLines: true,
            showTickMarks: true,
            showCrosshair: true,
            showGrid: true,
            xAxis: { interval, timezone },
            yAxis: { tickFormatter: formatTick },
            tooltip: { placement: 'cursor', valueFormatter: (value) => formatTick(value) },
        }),
        [timezone, interval, formatTick]
    )

    return (
        <Card title={title} className="min-w-0">
            <CardState
                loading={loading}
                isEmpty={isEmpty}
                skeleton={<Skeleton className="min-h-[240px] flex-1" />}
                empty={<NoDataMessage />}
            >
                <div className="flex min-h-[240px] flex-1 flex-col">
                    <TimeSeriesLineChart series={series} labels={labels} config={config} theme={theme} />
                </div>
            </CardState>
        </Card>
    )
}
