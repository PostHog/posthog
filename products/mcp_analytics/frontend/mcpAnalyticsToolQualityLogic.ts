import { actions, kea, path, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyMathType } from '~/types'

import toolQualityQueryTemplate from '../backend/templates/tool_quality.sql?raw'
import type { mcpAnalyticsToolQualityLogicType } from './mcpAnalyticsToolQualityLogicType'

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
    }),

    selectors({
        toolQualityQuery: [
            (s) => [s.dateFilter, s.toolQualitySort],
            (dateFilter: DateFilter, sort: SortState): DataTableNode => {
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
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): InsightVizNode => ({
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
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): InsightVizNode => ({
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
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): InsightVizNode => ({
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
])
