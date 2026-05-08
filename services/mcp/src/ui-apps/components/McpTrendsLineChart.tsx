import type { ReactElement } from 'react'

import { TimeSeriesLineChart } from 'lib/hog-charts/charts/TimeSeriesLineChart/TimeSeriesLineChart'
import type { Series } from 'lib/hog-charts/core/types'
import type { XAxisConfig } from 'lib/hog-charts/utils/use-axis-formatters'

import { MCP_CHART_THEME } from './McpChartTheme'
import type { TrendsInterval, TrendsResultItem } from './types'
import { formatDate, formatNumber, getSeriesLabel } from './utils'

export interface McpTrendsLineChartProps {
    results: TrendsResultItem[]
    interval?: TrendsInterval
    timezone?: string
}

export function McpTrendsLineChart({ results, interval, timezone }: McpTrendsLineChartProps): ReactElement | null {
    if (results.length === 0) {
        return null
    }

    const palette = MCP_CHART_THEME.colors
    const series: Series[] = results.map((item, index) => ({
        key: String(index),
        label: getSeriesLabel(item, index),
        data: item.data ?? [],
        color: palette[index % palette.length],
    }))

    const labels = results[0]?.days ?? results[0]?.labels ?? []

    // Prefer the auto formatter (interval-aware ticks: "14:00" / "Mar 5" / "Mar 2026").
    // Fall back to the static MCP formatter when `interval` or `timezone` is missing —
    // both come from upstream, so older tools or non-cached query paths still render.
    const xAxis: XAxisConfig =
        interval && timezone ? { interval, timezone } : { tickFormatter: (label) => formatDate(label) }

    return (
        <TimeSeriesLineChart
            series={series}
            labels={labels}
            theme={MCP_CHART_THEME}
            config={{
                showCrosshair: true,
                xAxis,
                yAxis: { tickFormatter: (value) => formatNumber(value), showGrid: true },
            }}
        />
    )
}
