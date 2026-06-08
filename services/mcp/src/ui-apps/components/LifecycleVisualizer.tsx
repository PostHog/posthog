import { type ReactElement, useMemo } from 'react'

import { emptyStateIllustration } from '@posthog/mcp-ui'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@posthog/quill'
import { ChartLegend, TimeSeriesBarChart, legendItemsFromSeries } from '@posthog/quill-charts'

import {
    buildTrendsLifecycleConfig,
    buildTrendsLifecycleSeries,
} from 'products/product_analytics/frontend/insights/trends/TrendsLifecycleChart/trendsLifecycleChartTransforms'

import { CHART_THEME } from './charts/theme'
import type { LifecycleResultItem, LifecycleStatus, LifecycleVisualizerProps } from './types'
import { formatDate } from './utils'

// Conventional lifecycle bucket colors — mirrors --color-lifecycle-* in frontend/src/styles/base.scss.
// Canvas can't read CSS variables, so we hand the chart concrete hexes via the injected `getColor`.
const LIFECYCLE_COLORS: Record<LifecycleStatus, string> = {
    new: '#1d4aff',
    returning: '#388600',
    resurrecting: '#a56eff',
    dormant: '#db3707',
}

const LIFECYCLE_TOOLTIP_CONFIG = { pinnable: true, placement: 'top' as const }

const lifecycleColor = (status: string | undefined): string =>
    LIFECYCLE_COLORS[(status ?? 'new') as LifecycleStatus] ?? LIFECYCLE_COLORS.new

export function LifecycleVisualizer({ query, results }: LifecycleVisualizerProps): ReactElement {
    const isStacked = query?.lifecycleFilter?.stacked ?? true
    const showLegend = query?.lifecycleFilter?.showLegend ?? true
    const toggledLifecycles = query?.lifecycleFilter?.toggledLifecycles

    const { series, labels } = useMemo(() => {
        const items = results ?? []
        // The backend always returns all four buckets; `toggledLifecycles` is a client-side filter in
        // the main app that hides the toggled-off ones. Mirror that by dropping them before building.
        const visible = items.filter(
            (item: LifecycleResultItem) =>
                !toggledLifecycles || (item.status && toggledLifecycles.includes(item.status))
        )
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
