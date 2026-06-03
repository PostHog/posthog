import type { ReactElement } from 'react'

import {
    ciRanges,
    type ConfidenceIntervalConfig,
    type MovingAverageConfig,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TrendLineConfig,
    type XAxisConfig,
    type YAxisConfig,
} from '@posthog/quill-charts'

import { buildMcpChartTheme } from './charts/quillChart'
import type { YUnit } from './ChartSettings'
import type { TrendsInterval, TrendsResultItem } from './types'
import { formatDate, getSeriesLabel } from './utils'

const MOVING_AVERAGE_WINDOW = 7
const CONFIDENCE_LEVEL = 0.95
const DEFAULT_CURRENCY = 'USD'

const AREA_FILL_OPACITY = 0.3

export interface McpTrendsLineChartProps {
    results: TrendsResultItem[]
    interval?: TrendsInterval | undefined
    timezone?: string | undefined
    fillArea?: boolean
    showTrendLine?: boolean
    showMovingAverage?: boolean
    showValueLabels?: boolean
    showConfidenceIntervals?: boolean
    percentStack?: boolean
    yUnit?: YUnit
}

export function McpTrendsLineChart({
    results,
    interval,
    timezone,
    fillArea = false,
    showTrendLine = false,
    showMovingAverage = false,
    showValueLabels = false,
    showConfidenceIntervals = false,
    percentStack = false,
    yUnit = 'numeric',
}: McpTrendsLineChartProps): ReactElement | null {
    if (results.length === 0) {
        return null
    }

    const theme = buildMcpChartTheme()
    const palette = theme.colors
    const series: Series[] = results.map((item, index) => ({
        key: String(index),
        label: getSeriesLabel(item, index),
        data: item.data ?? [],
        color: palette[index % palette.length],
        ...(fillArea ? { fill: { opacity: AREA_FILL_OPACITY } } : {}),
    }))

    const labels = results[0]?.days ?? results[0]?.labels ?? []

    const xAxis: XAxisConfig =
        interval && timezone ? { interval, timezone } : { tickFormatter: (label) => formatDate(label) }

    const yAxis: YAxisConfig = {
        format: yUnit,
        ...(yUnit === 'currency' ? { currency: DEFAULT_CURRENCY } : {}),
        showGrid: true,
    }

    const trendLines: TrendLineConfig[] | undefined = showTrendLine
        ? series.map((s) => ({ seriesKey: s.key, kind: 'linear' }))
        : undefined
    const movingAverage: MovingAverageConfig[] | undefined = showMovingAverage
        ? series.map((s) => ({ seriesKey: s.key, window: MOVING_AVERAGE_WINDOW }))
        : undefined
    const confidenceIntervals: ConfidenceIntervalConfig[] | undefined = showConfidenceIntervals
        ? series.map((s) => {
              const [lower, upper] = ciRanges(s.data, CONFIDENCE_LEVEL)
              return { seriesKey: s.key, lower, upper }
          })
        : undefined

    const config: TimeSeriesLineChartConfig = {
        showCrosshair: true,
        xAxis,
        yAxis,
        ...(trendLines ? { trendLines } : {}),
        ...(movingAverage ? { movingAverage } : {}),
        ...(confidenceIntervals ? { confidenceIntervals } : {}),
        ...(showValueLabels ? { valueLabels: true } : {}),
        ...(percentStack ? { percentStackView: true } : {}),
    }

    return <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
}
