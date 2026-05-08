import type { ReactElement } from 'react'

import {
    type MovingAverageConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TrendLineConfig,
} from 'lib/hog-charts/charts/TimeSeriesLineChart/TimeSeriesLineChart'
import type { Series } from 'lib/hog-charts/core/types'
import type { XAxisConfig } from 'lib/hog-charts/utils/use-axis-formatters'

import { MCP_CHART_THEME } from './McpChartTheme'
import type { TrendsInterval, TrendsResultItem } from './types'
import { formatDate, formatNumber, getSeriesLabel } from './utils'

const MOVING_AVERAGE_WINDOW = 7

export interface McpTrendsLineChartProps {
    results: TrendsResultItem[]
    interval?: TrendsInterval
    timezone?: string
    showTrendLine?: boolean
    showMovingAverage?: boolean
    showValueLabels?: boolean
    percentStack?: boolean
}

export function McpTrendsLineChart({
    results,
    interval,
    timezone,
    showTrendLine = false,
    showMovingAverage = false,
    showValueLabels = false,
    percentStack = false,
}: McpTrendsLineChartProps): ReactElement | null {
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

    const trendLines: TrendLineConfig[] | undefined = showTrendLine
        ? series.map((s) => ({ seriesKey: s.key, kind: 'linear' }))
        : undefined
    const movingAverage: MovingAverageConfig[] | undefined = showMovingAverage
        ? series.map((s) => ({ seriesKey: s.key, window: MOVING_AVERAGE_WINDOW }))
        : undefined

    const config: TimeSeriesLineChartConfig = {
        showCrosshair: true,
        xAxis,
        yAxis: { tickFormatter: (value) => formatNumber(value), showGrid: true },
        ...(trendLines ? { trendLines } : {}),
        ...(movingAverage ? { movingAverage } : {}),
        ...(showValueLabels ? { valueLabels: true } : {}),
        ...(percentStack ? { percentStackView: true } : {}),
    }

    return <TimeSeriesLineChart series={series} labels={labels} theme={MCP_CHART_THEME} config={config} />
}
