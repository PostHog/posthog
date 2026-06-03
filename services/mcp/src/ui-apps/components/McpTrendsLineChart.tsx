import type { ReactElement } from 'react'

import type { XAxisConfig, YAxisConfig } from '@posthog/quill-charts'

import { TrendsLineChartView } from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChartView'

import { buildMcpChartTheme } from './charts/shared'
import type { YUnit } from './ChartSettings'
import type { TrendsInterval, TrendsResultItem } from './types'
import { formatDate, getSeriesLabel } from './utils'

const MOVING_AVERAGE_WINDOW = 7
// `TrendsLineChartView` expects the confidence level as a 0–100 percentage.
const CONFIDENCE_LEVEL = 95
const DEFAULT_CURRENCY = 'USD'

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
    const labels = results[0]?.days ?? results[0]?.labels ?? []

    const xAxis: XAxisConfig =
        interval && timezone ? { interval, timezone } : { tickFormatter: (label) => formatDate(label) }

    const yAxis: YAxisConfig = {
        format: yUnit,
        ...(yUnit === 'currency' ? { currency: DEFAULT_CURRENCY } : {}),
        showGrid: true,
    }

    return (
        <TrendsLineChartView
            results={results.map((item, index) => ({ ...item, id: index, data: item.data ?? [] }))}
            labels={labels}
            theme={theme}
            getColor={(_, index) => theme.colors[index % theme.colors.length] ?? theme.colors[0] ?? '#1d4aff'}
            getLabel={getSeriesLabel}
            display={fillArea ? 'ActionsAreaGraph' : undefined}
            showTrendLines={showTrendLine}
            showMovingAverage={showMovingAverage}
            movingAverageIntervals={MOVING_AVERAGE_WINDOW}
            showConfidenceIntervals={showConfidenceIntervals}
            confidenceLevel={CONFIDENCE_LEVEL}
            xAxis={xAxis}
            yAxis={yAxis}
            valueLabels={showValueLabels}
            percentStackView={percentStack}
            showCrosshair
        />
    )
}
