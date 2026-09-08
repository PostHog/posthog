import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { SERVICE_NAME_KEY } from './metricsAttributes'

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

/**
 * Ingest promotes `service.name` to a column, but a group-by carries whichever spelling the user
 * picked, so both reach the results as label keys.
 */
const SERVICE_LABEL_KEYS = [SERVICE_NAME_KEY, 'service.name']

/** At most this many services in the Related menu — a wide group-by would otherwise fill the screen. */
export const MAX_CORRELATION_SERVICES = 12

/**
 * The services a logs or traces pivot can be scoped to, given what the chart currently shows.
 *
 * A pinned service filter is the user's stated scope, so it wins. Failing that, a chart grouped by
 * service names its own services. With neither, there is nothing honest to link to: an unscoped
 * jump into logs lands on every service in the project, which reads as a broken link.
 */
export const correlationServiceNames = (
    selectedServices: string[],
    seriesLabels: Record<string, string>[]
): string[] => {
    // `selectedServices` reports the "unknown service" chip as an empty string, which is a real
    // selection in metrics but cannot be expressed as a logs or traces service filter.
    const pinned = selectedServices.filter(Boolean)
    if (pinned.length) {
        return pinned.slice(0, MAX_CORRELATION_SERVICES)
    }

    const grouped = new Set<string>()
    for (const labels of seriesLabels) {
        for (const key of SERVICE_LABEL_KEYS) {
            if (labels[key]) {
                grouped.add(labels[key])
            }
        }
    }
    return [...grouped].sort().slice(0, MAX_CORRELATION_SERVICES)
}

/** "Show me this service's metrics", the pivot Logs and Tracing offer. */
export const metricsUrlForService = (serviceName: string, params: Omit<MetricLinkParams, 'filterGroup'> = {}): string =>
    metricUrl({
        ...params,
        filterGroup: metricsFilterGroup([{ key: SERVICE_NAME_KEY, value: [serviceName] }]),
    })
