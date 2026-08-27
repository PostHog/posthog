import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { SERVICE_NAME_KEY } from './components/metricsViewerLogic'

/**
 * The metrics viewer's URL contract, in one place.
 *
 * Every product that links into a metric goes through here rather than hand-writing the search
 * params, so the encoding stays in step with `metricsSceneLogic`'s parser. Mirrors
 * `products/tracing/frontend/traceLinks.ts`.
 */
export interface MetricLinkParams {
    metricName?: string
    /** Pins the series shape when one name is reported as several OTel types. */
    metricType?: string
    aggregation?: string
    dateFrom?: string | null
    dateTo?: string | null
    groupBy?: string[]
    filterGroup?: UniversalFiltersGroup
}

/** Wraps label matchers in the two-level group the filter bar and the scene parser both expect. */
export const metricsFilterGroup = (
    filters: { key: string; value: string[]; operator?: PropertyOperator }[]
): UniversalFiltersGroup => ({
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: filters.map(({ key, value, operator }) => ({
                type: PropertyFilterType.MetricAttribute,
                key,
                value,
                operator: operator ?? PropertyOperator.Exact,
            })) as UniversalFiltersGroup['values'],
        },
    ],
})

export const metricUrl = (params: MetricLinkParams): string => {
    const searchParams: Record<string, string | string[]> = {}

    if (params.metricName) {
        searchParams.metricName = params.metricName
    }
    if (params.metricType) {
        searchParams.metricType = params.metricType
    }
    if (params.aggregation) {
        searchParams.aggregation = params.aggregation
    }
    if (params.dateFrom) {
        searchParams.dateFrom = params.dateFrom
    }
    if (params.dateTo) {
        searchParams.dateTo = params.dateTo
    }
    if (params.groupBy?.length) {
        searchParams.groupBy = params.groupBy
    }
    if (params.filterGroup) {
        searchParams.filterGroup = JSON.stringify(params.filterGroup)
    }

    // The scene opens on Overview. Anything that scopes the viewer — a metric, a service filter, a
    // group-by, a window — means to show the chart, so say so rather than filtering a hidden tab.
    if (Object.keys(searchParams).length > 0) {
        searchParams.activeTab = 'viewer'
    }

    return combineUrl(urls.metrics(), searchParams).url
}

/** "Show me this service's metrics", the pivot Logs and Tracing offer. */
export const metricsUrlForService = (serviceName: string, params: Omit<MetricLinkParams, 'filterGroup'> = {}): string =>
    metricUrl({
        ...params,
        filterGroup: metricsFilterGroup([{ key: SERVICE_NAME_KEY, value: [serviceName] }]),
    })
