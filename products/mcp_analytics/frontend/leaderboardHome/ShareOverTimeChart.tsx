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

import { useChartConfig } from 'lib/charts/hooks'
import { formatPercentage } from 'lib/utils/numbers'

import { formatNumber } from '../dashboard/formatters'

export interface ShareOverTimeSeries {
    key: string
    label: string
    color: string | undefined
    data: number[]
}

export function ShareOverTimeChart({
    labels,
    series,
    theme,
    timezone,
    interval,
}: {
    labels: string[]
    series: ShareOverTimeSeries[]
    theme: ChartTheme
    timezone: string
    interval: TimeInterval
}): JSX.Element {
    const chartSeries = useMemo<Series[]>(
        () =>
            series.map((s) => ({ key: s.key, label: s.label, color: s.color, data: s.data, fill: { opacity: 0.85 } })),
        [series]
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
        <div className="flex min-h-[300px] flex-1 flex-col">
            {/* Min height on the plot so a wrapping legend grows the card. */}
            <TimeSeriesLineChart
                series={chartSeries}
                labels={labels}
                config={config}
                theme={theme}
                tooltip={renderTooltip}
                className="min-h-[276px]!"
            />
        </div>
    )
}

function formatCalls(calls: number): string {
    return `${formatNumber(calls)} ${calls === 1 ? 'call' : 'calls'}`
}
