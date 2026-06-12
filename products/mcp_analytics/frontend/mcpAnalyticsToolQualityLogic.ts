import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { hogqlQuery } from '@posthog/query-frontend/query'
import { DataTableNode, InsightVizNode, NodeKind } from '@posthog/query-frontend/schema/schema-general'
import { hogql } from '@posthog/query-frontend/utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import {
    type AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import toolQualityQueryTemplate from '../backend/templates/tool_quality.sql?raw'
import type { mcpAnalyticsToolQualityLogicType } from './mcpAnalyticsToolQualityLogicType'

// `$mcp_tool_category` is stamped onto every mcp_tool_call event by the producer
// (PostHog's MCP server from its catalog; external servers via the SDK). We read
// the available categories straight from the data so the scope selector works for
// any project's taxonomy without a hardcoded tool→category map.
const CATEGORIES_QUERY = hogql`
SELECT DISTINCT toString(properties.$mcp_tool_category) AS category
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 30 DAY
    AND properties.$mcp_tool_category IS NOT NULL
    AND properties.$mcp_tool_category != ''
ORDER BY category
`

// Per-category call counts over a fixed 7-day window powering the "share of MCP
// usage" headline. Rows with an empty category count toward the total but not the
// in-scope numerator, so uncategorized traffic dilutes the share as expected.
const CATEGORY_COUNTS_QUERY = hogql`
SELECT toString(properties.$mcp_tool_category) AS category, count() AS calls
FROM events
WHERE event = 'mcp_tool_call'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY category
`

export interface CategoryCount {
    category: string
    calls: number
}

export interface ScopeShare {
    inScope: number
    total: number
    pct: number | null
}

export type SortDirection = 'ASC' | 'DESC'

export interface SortState {
    column: string
    direction: SortDirection
}

export interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

const DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }
const DEFAULT_SORT: SortState = { column: 'total_calls', direction: 'DESC' }

export const mcpAnalyticsToolQualityLogic = kea<mcpAnalyticsToolQualityLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsToolQualityLogic']),

    actions({
        setToolQualitySort: (column: string, direction: SortDirection) => ({ column, direction }),
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSelectedCategories: (categories: string[]) => ({ categories }),
    }),

    reducers({
        toolQualitySort: [
            DEFAULT_SORT,
            {
                setToolQualitySort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
        dateFilter: [
            DEFAULT_DATE_FILTER,
            {
                setDateFilter: (_, { dateFrom, dateTo }): DateFilter => ({ dateFrom, dateTo }),
            },
        ],
        selectedCategories: [
            [] as string[],
            {
                setSelectedCategories: (_, { categories }): string[] => categories,
            },
        ],
    }),

    loaders({
        availableCategories: [
            [] as string[],
            {
                loadAvailableCategories: async (): Promise<string[]> => {
                    const response = await hogqlQuery(CATEGORIES_QUERY)
                    return ((response?.results as unknown[][]) ?? []).map((r) => String(r[0] ?? '')).filter(Boolean)
                },
            },
        ],
        categoryCounts: [
            [] as CategoryCount[],
            {
                loadCategoryCounts: async (): Promise<CategoryCount[]> => {
                    const response = await hogqlQuery(CATEGORY_COUNTS_QUERY)
                    return ((response?.results as unknown[][]) ?? []).map((r) => ({
                        category: String(r[0] ?? ''),
                        calls: Number(r[1] ?? 0),
                    }))
                },
            },
        ],
    }),

    selectors({
        // Event property filter applied to every query so the whole tab scopes to
        // the selected categories. Empty selection means "all categories".
        categoryProperties: [
            (s) => [s.selectedCategories],
            (selectedCategories: string[]): AnyPropertyFilter[] =>
                selectedCategories.length > 0
                    ? [
                          {
                              key: '$mcp_tool_category',
                              value: selectedCategories,
                              operator: PropertyOperator.Exact,
                              type: PropertyFilterType.Event,
                          },
                      ]
                    : [],
        ],
        scopeShare: [
            (s) => [s.categoryCounts, s.selectedCategories],
            (categoryCounts: CategoryCount[], selectedCategories: string[]): ScopeShare => {
                const total = categoryCounts.reduce((acc, row) => acc + row.calls, 0)
                const selected = new Set(selectedCategories)
                const inScope = categoryCounts
                    .filter((row) => selected.has(row.category))
                    .reduce((acc, row) => acc + row.calls, 0)
                return { inScope, total, pct: total > 0 ? (inScope / total) * 100 : null }
            },
        ],
        toolQualityQuery: [
            (s) => [s.dateFilter, s.toolQualitySort, s.categoryProperties],
            (dateFilter: DateFilter, sort: SortState, categoryProperties: AnyPropertyFilter[]): DataTableNode => {
                const query = toolQualityQueryTemplate
                    .replace('__ORDER_BY__', sort.column)
                    .replace('__ORDER_DIRECTION__', sort.direction)

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query,
                        filters: {
                            dateRange: {
                                date_from: dateFilter.dateFrom,
                                date_to: dateFilter.dateTo,
                            },
                            ...(categoryProperties.length > 0 ? { properties: categoryProperties } : {}),
                        },
                    },
                    columns: [
                        'tool',
                        'total_calls',
                        'error_rate_pct',
                        'p95_duration_ms',
                        'p50_duration_ms',
                        'users',
                        'sessions',
                        'last_seen',
                    ],
                    showDateRange: true,
                    showReload: true,
                    showSearch: true,
                    showPropertyFilter: [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ],
                    showExport: true,
                    showColumnConfigurator: true,
                    allowSorting: true,
                }
            },
        ],
        topToolsQuery: [
            (s) => [s.dateFilter, s.categoryProperties],
            (dateFilter: DateFilter, categoryProperties: AnyPropertyFilter[]): InsightVizNode => ({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: 'mcp_tool_call',
                            name: 'mcp_tool_call',
                            math: BaseMathType.TotalCount,
                        },
                    ],
                    properties: categoryProperties,
                    breakdownFilter: {
                        breakdown_type: 'event',
                        breakdown: '$mcp_tool_name',
                        breakdown_limit: 10,
                    },
                    trendsFilter: {
                        display: ChartDisplayType.ActionsPie,
                        showLegend: false,
                        showValuesOnSeries: true,
                        showPercentStackView: true,
                    },
                    dateRange: {
                        date_from: dateFilter.dateFrom,
                        date_to: dateFilter.dateTo,
                    },
                },
                vizSpecificOptions: { ActionsPie: { hideAggregation: true } },
            }),
        ],
        errorTrendQuery: [
            (s) => [s.dateFilter, s.categoryProperties],
            (dateFilter: DateFilter, categoryProperties: AnyPropertyFilter[]): InsightVizNode => ({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: 'mcp_tool_call',
                            name: 'mcp_tool_call',
                            math: BaseMathType.TotalCount,
                        },
                    ],
                    properties: categoryProperties,
                    breakdownFilter: {
                        breakdown_type: 'event',
                        breakdown: '$mcp_is_error',
                    },
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                    },
                    dateRange: {
                        date_from: dateFilter.dateFrom,
                        date_to: dateFilter.dateTo,
                    },
                },
            }),
        ],
        durationTrendQuery: [
            (s) => [s.dateFilter, s.categoryProperties],
            (dateFilter: DateFilter, categoryProperties: AnyPropertyFilter[]): InsightVizNode => ({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: 'mcp_tool_call',
                            name: 'p95 duration (ms)',
                            math: PropertyMathType.P95,
                            math_property: '$mcp_duration_ms',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: 'mcp_tool_call',
                            name: 'p50 duration (ms)',
                            math: PropertyMathType.Median,
                            math_property: '$mcp_duration_ms',
                        },
                    ],
                    properties: categoryProperties,
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                    },
                    dateRange: {
                        date_from: dateFilter.dateFrom,
                        date_to: dateFilter.dateTo,
                    },
                },
            }),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadAvailableCategories()
        actions.loadCategoryCounts()
    }),
])
