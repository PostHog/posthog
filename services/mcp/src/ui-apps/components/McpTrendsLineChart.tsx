import type { ReactElement } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig, XAxisConfig, YAxisConfig } from '@posthog/quill-charts'

import {
    buildDerivedConfigs,
    buildTrendsSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsSeriesTransforms'

import { buildMcpChartTheme } from './charts/shared'
import type { YUnit } from './ChartSettings'
import type { TrendsInterval, TrendsResultItem } from './types'
import { formatDate, getSeriesLabel } from './utils'

const MOVING_AVERAGE_WINDOW = 7
// The shared transforms expect the confidence level as a 0–100 percentage.
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
    const mappedResults = results.map((item, index) => ({ ...item, id: index, data: item.data ?? [] }))

    const series: Series[] = buildTrendsSeries(mappedResults, {
        getColor: (_, index) => theme.colors[index % theme.colors.length] ?? theme.colors[0] ?? '#1d4aff',
        getLabel: getSeriesLabel,
        ...(fillArea ? { display: 'ActionsAreaGraph' } : {}),
    })

    const derived = buildDerivedConfigs(mappedResults, {
        showTrendLines: showTrendLine,
        showMovingAverage,
        movingAverageIntervals: MOVING_AVERAGE_WINDOW,
        showConfidenceIntervals,
        confidenceLevel: CONFIDENCE_LEVEL,
    })

    const xAxis: XAxisConfig =
        interval && timezone ? { interval, timezone } : { tickFormatter: (label) => formatDate(label) }

    const yAxis: YAxisConfig = {
        format: yUnit,
        ...(yUnit === 'currency' ? { currency: DEFAULT_CURRENCY } : {}),
        showGrid: true,
    }

    const config: TimeSeriesLineChartConfig = {
        ...derived,
        xAxis,
        yAxis,
        valueLabels: showValueLabels,
        ...(percentStack ? { percentStackView: true } : {}),
        showCrosshair: true,
    }

    return <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
}
