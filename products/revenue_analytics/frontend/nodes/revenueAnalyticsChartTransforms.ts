import type { LegendItem, Series } from '@posthog/quill-charts'

import type { GraphDataset } from '~/types'

import type { TrendsSeriesMeta } from 'products/product_analytics/frontend/insights/trends/shared/trendsSeriesMeta'

export type RevenueAnalyticsChartKind = 'line' | 'area' | 'bar'

export interface BuildRevenueAnalyticsSeriesOpts {
    kind: RevenueAnalyticsChartKind
    isInProgress?: boolean
    getColor?: (dataset: GraphDataset, index: number) => string | undefined
}

export function buildRevenueAnalyticsSeries(
    datasets: GraphDataset[],
    opts: BuildRevenueAnalyticsSeriesOpts
): Series<TrendsSeriesMeta>[] {
    const { kind, isInProgress = false, getColor } = opts
    return datasets.map((dataset, index) => {
        const data = (dataset.data ?? []) as number[]
        const dashFromIndex = isInProgress && kind !== 'bar' && data.length > 1 ? data.length - 1 : undefined
        return {
            key: String(dataset.id ?? index),
            label: dataset.label ?? '',
            data,
            color: getColor?.(dataset, index),
            fill: kind === 'area' ? {} : undefined,
            stroke: dashFromIndex !== undefined ? { partial: { fromIndex: dashFromIndex } } : undefined,
            meta: {
                action: dataset.action,
                breakdown_value: dataset.breakdown_value,
                days: dataset.days,
                order: dataset.action?.order ?? index,
            },
        }
    })
}

// Stacked charts draw the first series at the bottom but list it at the top of the legend;
// reversing keeps the legend reading top-down in the same visual order as the stack.
export function orderLegendItems(items: LegendItem[], reverse?: boolean): LegendItem[] {
    return reverse ? [...items].reverse() : items
}
