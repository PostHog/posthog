import { type MetricSummary } from 'lib/components/Metric/metricSummary'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { MetricAggregation, MetricsViewMode } from './metricsViewerLogic'

export type MetricsViewerSavedFilters = {
    metricName?: string
    aggregation?: MetricAggregation
    dateFrom?: string | null
    dateTo?: string | null
    filters?: UniversalFiltersGroup
    groupBy?: string[]
    viewMode?: MetricsViewMode
    statSummary?: MetricSummary
}

const AGGREGATIONS: MetricAggregation[] = ['sum', 'avg', 'count', 'p95', 'rate', 'increase']
const VIEW_MODES: MetricsViewMode[] = ['chart', 'stat']
const STAT_SUMMARIES: MetricSummary[] = ['latest', 'average', 'total']

export const isValidAggregation = (value: unknown): value is MetricAggregation =>
    AGGREGATIONS.includes(value as MetricAggregation)

export const isValidViewMode = (value: unknown): value is MetricsViewMode =>
    VIEW_MODES.includes(value as MetricsViewMode)

export const isValidStatSummary = (value: unknown): value is MetricSummary =>
    STAT_SUMMARIES.includes(value as MetricSummary)

const isGroupLike = (value: unknown): boolean =>
    typeof value === 'object' &&
    value !== null &&
    'type' in value &&
    (value.type === FilterLogicalOperator.And || value.type === FilterLogicalOperator.Or)

// Validates the persisted/URL filter blob recursively. A saved view is a free-form blob a
// teammate could have written malformed (e.g. a nested group missing `values`); rejecting it
// here keeps bad data out of state so the viewer's filter flattening never throws.
export const isValidFilterGroup = (value: unknown): value is UniversalFiltersGroup => {
    if (typeof value !== 'object' || value === null || !('type' in value) || !('values' in value)) {
        return false
    }
    if (!isGroupLike(value) || !Array.isArray(value.values)) {
        return false
    }
    return value.values.every((child) =>
        isGroupLike(child) ? isValidFilterGroup(child) : typeof child === 'object' && child !== null
    )
}
