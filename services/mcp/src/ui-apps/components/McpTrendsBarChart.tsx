import type { ReactElement } from 'react'

import {
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    type XAxisConfig,
    type YAxisConfig,
} from '@posthog/quill-charts'

import { buildMcpChartTheme } from './charts/shared'
import type { YUnit } from './ChartSettings'
import type { TrendsInterval, TrendsResultItem } from './types'
import { formatDate, getSeriesLabel } from './utils'

const DEFAULT_CURRENCY = 'USD'

export type BarLayout = 'grouped' | 'stacked' | 'percent'

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
    }))

    const labels = results[0]?.days ?? results[0]?.labels ?? []

    const xAxis: XAxisConfig =
        interval && timezone ? { interval, timezone } : { tickFormatter: (label) => formatDate(label) }

    const yAxis: YAxisConfig = {
        format: yUnit,
        ...(yUnit === 'currency' ? { currency: DEFAULT_CURRENCY } : {}),
        showGrid: true,
    }

    const config: TimeSeriesBarChartConfig = {
        barLayout,
        xAxis,
        yAxis,
        ...(showValueLabels ? { valueLabels: true } : {}),
    }

    return <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
}
