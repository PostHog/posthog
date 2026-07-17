import { type ReactElement } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import {
    DefaultTooltip,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
} from '@posthog/quill-charts'

import { ChartHeader } from './ChartHeader'
import { colorAt, useMcpChartTheme } from './charts/theme'
import type { StickinessVisualizerProps } from './types'
import { getSeriesLabel } from './utils'

const TITLE = 'Stickiness'

const STICKINESS_TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }

// The backend returns absolute actor counts per bucket; stickiness reads each bucket as its share
// of the series' total users (`count`). A zero-total series contributes 0% — never a raw count —
// so it can't plot unscaled values onto the percentage axis.
function toPercent(value: number, count: number): number {
    return count ? (value / count) * 100 : 0
}

function formatPercent(value: number): string {
    return `${value.toFixed(1)}%`
}

const renderStickinessTooltip = (ctx: TooltipContext): ReactElement => (
    <DefaultTooltip {...ctx} valueFormatter={(value) => formatPercent(value)} />
)

export function StickinessVisualizer({ query, results }: StickinessVisualizerProps): ReactElement {
    const theme = useMcpChartTheme()

    const hasData = results?.some((item) => item.count !== 0 && (item.data?.length ?? 0) > 0)
    if (!results || results.length === 0 || !hasData) {
        return (
            <div>
                <ChartHeader title={TITLE} />
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia>{emptyStateIllustration('chart')}</EmptyMedia>
                        <EmptyDescription>No data available</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    // X-axis is the interval-count distribution ("1 day", "2 days", …), not a time series. Prefer the
    // API's own bucket labels; synthesize "N {interval}s" from `days` when they're absent.
    const interval = query?.interval ?? 'day'
    const labels =
        results[0]?.labels ?? results[0]?.days?.map((d) => `${d} ${interval}${Number(d) === 1 ? '' : 's'}`) ?? []

    const series: Series[] = results.map((item, i) => ({
        key: String(i),
        label: getSeriesLabel(item, i),
        data: (item.data ?? []).map((value) => toPercent(value, item.count)),
        color: colorAt(i),
    }))

    const config: TimeSeriesLineChartConfig = {
        // No xAxis date config — labels are interval-count buckets, rendered verbatim.
        yAxis: { tickFormatter: formatPercent, showGrid: true },
        showCrosshair: true,
        tooltip: STICKINESS_TOOLTIP_CONFIG,
        legend: { show: series.length > 1, position: 'bottom' },
    }

    return (
        <div>
            <ChartHeader title={TITLE} />
            <div className="flex flex-col w-full h-[400px]">
                <TimeSeriesLineChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={config}
                    tooltip={renderStickinessTooltip}
                />
            </div>
        </div>
    )
}
