import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind, PathsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, ChartDisplayType, PathType, PropertyFilterType, PropertyOperator } from '~/types'

import toolsQueryTemplate from '../../backend/queries/tools.sql?raw'
import { SortDirection, SortState, llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsToolsLogicType } from './llmAnalyticsToolsLogicType'

export interface LLMAnalyticsToolsLogicProps {
    tabId?: string
}

export const llmAnalyticsToolsLogic = kea<llmAnalyticsToolsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsToolsLogic']),
    key((props: LLMAnalyticsToolsLogicProps) => props.tabId || 'default'),
    props({} as LLMAnalyticsToolsLogicProps),
    connect((props: LLMAnalyticsToolsLogicProps) => ({
        values: [
            llmAnalyticsSharedLogic({ tabId: props.tabId }),
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    })),

    actions({
        setToolsSort: (column: string, direction: SortDirection) => ({ column, direction }),
    }),

    reducers({
        toolsSort: [
            { column: 'total_calls', direction: 'DESC' } as SortState,
            {
                setToolsSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
    }),

    selectors({
        toolsQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters, s.toolsSort, s.groupsTaxonomicTypes],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                toolsSort: SortState,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[]
            ): DataTableNode => {
                const query = toolsQueryTemplate
                    .replace('__ORDER_BY__', toolsSort.column)
                    .replace('__ORDER_DIRECTION__', toolsSort.direction)

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query,
                        filters: {
                            dateRange: {
                                date_from: dateFilter.dateFrom || null,
                                date_to: dateFilter.dateTo || null,
                            },
                            filterTestAccounts: shouldFilterTestAccounts,
                            properties: propertyFilters,
                        },
                    },
                    columns: [
                        'tool',
                        'total_calls',
                        'traces',
                        'users',
                        'sessions',
                        'days_seen',
                        'single_pct',
                        'first_seen',
                        'last_seen',
                    ],
                    showDateRange: true,
                    showReload: true,
                    showSearch: true,
                    showPropertyFilter: [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ],
                    showTestAccountFilters: true,
                    showExport: true,
                    showColumnConfigurator: true,
                    allowSorting: true,
                }
            },
        ],
        buildToolPathsQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): ((toolName: string) => PathsQuery) => {
                return (toolName: string): PathsQuery => ({
                    kind: NodeKind.PathsQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || null,
                        date_to: dateFilter.dateTo || null,
                    },
                    filterTestAccounts: shouldFilterTestAccounts,
                    properties: [
                        ...propertyFilters,
                        {
                            key: '$ai_tools_called',
                            operator: PropertyOperator.IsSet,
                            type: PropertyFilterType.Event,
                        },
                    ],
                    pathsFilter: {
                        includeEventTypes: [PathType.HogQL],
                        pathsHogQLExpression: "arrayJoin(splitByChar(',', ifNull(properties.$ai_tools_called, '')))",
                        startPoint: toolName,
                        stepLimit: 5,
                        edgeLimit: 50,
                    },
                })
            },
        ],
        buildToolSequencesQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): ((toolName: string) => TrendsQuery) => {
                return (toolName: string): TrendsQuery => ({
                    kind: NodeKind.TrendsQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || null,
                        date_to: dateFilter.dateTo || null,
                    },
                    filterTestAccounts: shouldFilterTestAccounts,
                    properties: propertyFilters,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_generation',
                            properties: [
                                {
                                    key: '$ai_tools_called',
                                    operator: PropertyOperator.Regex,
                                    value: `(^|,)${toolName}(,|$)`,
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                    breakdownFilter: {
                        breakdown:
                            "arrayStringConcat(arraySort(arrayDistinct(splitByChar(',', ifNull(properties.$ai_tools_called, '')))), ', ')",
                        breakdown_type: 'hogql',
                        breakdown_limit: 20,
                    },
                    trendsFilter: {
                        display: ChartDisplayType.ActionsBarValue,
                    },
                })
            },
        ],
        buildToolTrendQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): ((toolName: string) => TrendsQuery) => {
                return (toolName: string): TrendsQuery => ({
                    kind: NodeKind.TrendsQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || null,
                        date_to: dateFilter.dateTo || null,
                    },
                    filterTestAccounts: shouldFilterTestAccounts,
                    properties: propertyFilters,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_generation',
                            properties: [
                                {
                                    key: '$ai_tools_called',
                                    operator: PropertyOperator.Regex,
                                    value: `(^|,)${toolName}(,|$)`,
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                })
            },
        ],
    }),
])
