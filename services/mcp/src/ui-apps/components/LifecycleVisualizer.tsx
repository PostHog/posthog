import { type ReactElement, useMemo } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { Legend, TimeSeriesBarChart, legendItemsFromSeries } from '@posthog/quill-charts'

import { buildLifecycleChartModel } from 'products/product_analytics/frontend/insights/trends/TrendsLifecycleChart/trendsLifecycleChartTransforms'

import { ChartHeader } from './ChartHeader'
import { lifecycleColor, useMcpChartTheme } from './charts/theme'
import type { LifecycleVisualizerProps } from './types'
import { formatDate } from './utils'

const TITLE = 'Lifecycle'

const LIFECYCLE_TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }

export function LifecycleVisualizer({ query, results }: LifecycleVisualizerProps): ReactElement {
    const showLegend = query?.lifecycleFilter?.showLegend ?? true
    const theme = useMcpChartTheme()

    const { series, labels, config } = useMemo(
        () =>
            buildLifecycleChartModel(
                (results ?? []).map((item, i) => ({
                    id: i,
                    label: item.label,
                    data: item.data ?? [],
                    status: item.status,
                    days: item.days,
                })),
                {
                    getColor: lifecycleColor,
                    labels: (results?.[0]?.days ?? results?.[0]?.labels ?? []).map(formatDate),
                    isStacked: query?.lifecycleFilter?.stacked ?? true,
                    toggledLifecycles: query?.lifecycleFilter?.toggledLifecycles,
                    tooltip: LIFECYCLE_TOOLTIP_CONFIG,
                }
            ),
        [results, query?.lifecycleFilter?.stacked, query?.lifecycleFilter?.toggledLifecycles]
    )

    const legendItems = useMemo(() => legendItemsFromSeries(series, theme), [series, theme])

    if (!results || results.length === 0 || series.length === 0 || labels.length === 0) {
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

    // The chart box gets its width from a plain block (`w-full`) and an explicit height — not from
    // ChartLegend's `flex-1`/`self-stretch` slot, which can resolve to 0 at mount in the MCP iframe,
    // leaving the canvas measured at 0 and unpainted. Funnels/trends render the chart this way too.
    return (
        <div className="w-full">
            <ChartHeader title={TITLE} />
            {showLegend && legendItems.length > 0 && (
                <div className="mb-2">
                    <Legend items={legendItems} orientation="horizontal" align="center" />
                </div>
            )}
            <div className="flex flex-col w-full h-[400px]">
                <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
            </div>
        </div>
    )
}
