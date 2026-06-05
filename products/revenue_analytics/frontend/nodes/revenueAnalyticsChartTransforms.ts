import type { Series } from '@posthog/quill-charts'

import type { GraphDataset } from '~/types'

import type { TrendsSeriesMeta } from 'products/product_analytics/frontend/insights/trends/shared/trendsSeriesMeta'

export type RevenueAnalyticsChartKind = 'line' | 'area' | 'bar'

export interface BuildRevenueAnalyticsSeriesOpts {
    kind: RevenueAnalyticsChartKind
    // Dash the final segment to mark the still-incomplete current period (line/area only).
    isInProgress?: boolean
    // Override the per-series color (e.g. MRR breakdown maps status → fixed color). When omitted,
    // the chart falls back to the theme palette by series index, matching the legacy chart.
    getColor?: (dataset: GraphDataset, index: number) => string | undefined
}

export function buildRevenueAnalyticsSeries(
    datasets: GraphDataset[],
    opts: BuildRevenueAnalyticsSeriesOpts
): Series<TrendsSeriesMeta>[] {
    const { kind, isInProgress = false, getColor } = opts
    return datasets.map((dataset, index) => {
        const data = (dataset.data ?? []) as number[]
        // A two-point line is the minimum that has a final segment to dash; bars don't dash.
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
