import type { ReactElement } from 'react'

import { TimeSeriesBarChart } from 'lib/hog-charts/charts/TimeSeriesBarChart/TimeSeriesBarChart'
import type { Series } from 'lib/hog-charts/core/types'
import type { XAxisConfig } from 'lib/hog-charts/utils/use-axis-formatters'

import { MCP_CHART_THEME } from './McpChartTheme'
import type { TrendsInterval, TrendsResultItem } from './types'
import { formatDate, formatNumber, getSeriesLabel } from './utils'

export interface McpTrendsBarChartProps {
    results: TrendsResultItem[]
    interval?: TrendsInterval
    timezone?: string
}

export function McpTrendsBarChart({ results, interval, timezone }: McpTrendsBarChartProps): ReactElement | null {
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

    const xAxis: XAxisConfig =
        interval && timezone ? { interval, timezone } : { tickFormatter: (label) => formatDate(label) }

    return (
        <TimeSeriesBarChart
            series={series}
            labels={labels}
            theme={MCP_CHART_THEME}
            config={{
                barLayout: 'grouped',
                xAxis,
                yAxis: { tickFormatter: (value) => formatNumber(value), showGrid: true },
            }}
        />
    )
}
