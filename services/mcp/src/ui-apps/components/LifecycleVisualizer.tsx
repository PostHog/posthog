import { type ReactElement, useMemo } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { ChartLegend, TimeSeriesBarChart, legendItemsFromSeries } from '@posthog/quill-charts'

import {
    buildTrendsLifecycleConfig,
    buildTrendsLifecycleSeries,
    filterToggledLifecycleResults,
} from 'products/product_analytics/frontend/insights/trends/TrendsLifecycleChart/trendsLifecycleChartTransforms'

import { CHART_THEME, lifecycleColor } from './charts/theme'
import type { LifecycleVisualizerProps } from './types'
import { formatDate } from './utils'

const LIFECYCLE_TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }

export function LifecycleVisualizer({ query, results }: LifecycleVisualizerProps): ReactElement {
    const isStacked = query?.lifecycleFilter?.stacked ?? true
    const showLegend = query?.lifecycleFilter?.showLegend ?? true
    const toggledLifecycles = query?.lifecycleFilter?.toggledLifecycles

    const { series, labels } = useMemo(() => {
        const items = results ?? []
        const visible = filterToggledLifecycleResults(items, toggledLifecycles)
        const lifecycleSeries = buildTrendsLifecycleSeries(
            visible.map((item, i) => ({
                id: i,
                label: item.label,
                data: item.data ?? [],
                status: item.status,
                days: item.days,
            })),
            { getColor: lifecycleColor }
        )
        const rawLabels = items[0]?.days ?? items[0]?.labels ?? []
        return { series: lifecycleSeries, labels: rawLabels.map(formatDate) }
    }, [results, toggledLifecycles])

    const config = useMemo(
        () => buildTrendsLifecycleConfig({ isStacked, tooltip: LIFECYCLE_TOOLTIP_CONFIG }),
        [isStacked]
    )

    const legendItems = useMemo(() => legendItemsFromSeries(series, CHART_THEME), [series])

    if (!results || results.length === 0 || series.length === 0 || labels.length === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia>{emptyStateIllustration('chart')}</EmptyMedia>
                    <EmptyDescription>No data available</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <ChartLegend show={showLegend} items={legendItems} position="top">
            <div className="flex flex-col w-full h-[400px]">
                <TimeSeriesBarChart series={series} labels={labels} theme={CHART_THEME} config={config} />
            </div>
        </ChartLegend>
    )
}
