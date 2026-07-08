import { type MetricSummary } from 'lib/components/Metric/metricSummary'

import { UniversalFiltersGroup } from '~/types'

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

export const isValidFilterGroup = (value: unknown): value is UniversalFiltersGroup =>
    typeof value === 'object' && value !== null && 'type' in value && 'values' in value && Array.isArray(value.values)
