import { type ReactElement, useMemo } from 'react'

import { type Series, TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { buildTrendsSeries } from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsSeriesTransforms'

import { buildMcpChartTheme, buildMcpXAxis, buildMcpYAxis, mcpSeriesColor } from './charts/shared'
import type { YUnit } from './ChartSettings'
import type { TrendsInterval, TrendsResultItem } from './types'
import { getSeriesLabel } from './utils'

export type BarLayout = 'grouped' | 'stacked'

export interface McpTrendsBarChartProps {
    results: TrendsResultItem[]
    interval?: TrendsInterval | undefined
    timezone?: string | undefined
    barLayout?: BarLayout
    showValueLabels?: boolean
    yUnit?: YUnit
}

export function McpTrendsBarChart({
    results,
    interval,
    timezone,
    barLayout = 'grouped',
    showValueLabels = false,
    yUnit = 'numeric',
}: McpTrendsBarChartProps): ReactElement | null {
    const theme = useMemo(() => buildMcpChartTheme(), [])
    const labels = results[0]?.days ?? results[0]?.labels ?? []

    const series: Series[] = useMemo(
        () =>
            buildTrendsSeries(
                results.map((item, index) => ({ ...item, id: index, data: item.data ?? [] })),
                { getColor: (_, index) => mcpSeriesColor(theme, index), getLabel: getSeriesLabel }
            ),
        [results, theme]
    )

    const config: TimeSeriesBarChartConfig = useMemo(
        () => ({
            barLayout,
            xAxis: buildMcpXAxis(interval, timezone),
            yAxis: buildMcpYAxis(yUnit),
            ...(showValueLabels ? { valueLabels: true } : {}),
        }),
        [barLayout, interval, timezone, yUnit, showValueLabels]
    )

    if (results.length === 0) {
        return null
    }

    return <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
}
