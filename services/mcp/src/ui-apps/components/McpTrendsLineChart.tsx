import { type ReactElement, useMemo } from 'react'

import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'
import { TimeSeriesLineChart } from '@posthog/quill-charts'

import {
    buildDerivedConfigs,
    buildTrendsSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsSeriesTransforms'

import { buildMcpChartTheme, buildMcpXAxis, buildMcpYAxis, mcpSeriesColor } from './charts/shared'
import type { YUnit } from './ChartSettings'
import type { TrendsInterval, TrendsResultItem } from './types'
import { getSeriesLabel } from './utils'

const MOVING_AVERAGE_WINDOW = 7
// The shared transforms expect the confidence level as a 0–100 percentage.
const CONFIDENCE_LEVEL = 95

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
    const theme = useMemo(() => buildMcpChartTheme(), [])
    const labels = results[0]?.days ?? results[0]?.labels ?? []
    const mappedResults = useMemo(
        () => results.map((item, index) => ({ ...item, id: index, data: item.data ?? [] })),
        [results]
    )

    const series: Series[] = useMemo(
        () =>
            buildTrendsSeries(mappedResults, {
                getColor: (_, index) => mcpSeriesColor(theme, index),
                getLabel: getSeriesLabel,
                ...(fillArea ? { display: 'ActionsAreaGraph' } : {}),
            }),
        [mappedResults, theme, fillArea]
    )

    const config: TimeSeriesLineChartConfig = useMemo(
        () => ({
            ...buildDerivedConfigs(mappedResults, {
                showTrendLines: showTrendLine,
                showMovingAverage,
                movingAverageIntervals: MOVING_AVERAGE_WINDOW,
                showConfidenceIntervals,
                confidenceLevel: CONFIDENCE_LEVEL,
            }),
            xAxis: buildMcpXAxis(interval, timezone),
            yAxis: buildMcpYAxis(yUnit),
            valueLabels: showValueLabels,
            ...(percentStack ? { percentStackView: true } : {}),
            showCrosshair: true,
        }),
        [
            mappedResults,
            showTrendLine,
            showMovingAverage,
            showConfidenceIntervals,
            interval,
            timezone,
            yUnit,
            showValueLabels,
            percentStack,
        ]
    )

    if (results.length === 0) {
        return null
    }

    return <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
}
