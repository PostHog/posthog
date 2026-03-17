import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { escapeRegex } from 'lib/actionUtils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'
import {
    DataTableNode,
    DataVisualizationNode,
    InsightVizNode,
    NodeKind,
    PathsQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, ChartDisplayType, PathType, PropertyFilterType, PropertyOperator } from '~/types'

import aiEventsQueryTemplate from '../../backend/queries/tools.sql?raw'
import eventsQueryTemplate from '../../backend/queries/tools_events.sql?raw'
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
            featureFlagLogic,
            ['featureFlags'],
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
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.toolsSort,
                s.groupsTaxonomicTypes,
                s.featureFlags,
            ],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                toolsSort: SortState,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[],
                featureFlags: FeatureFlagsSet
            ): DataTableNode => {
                const useAiEvents = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_AI_EVENTS_TABLE_ROLLOUT]
                const template = useAiEvents ? aiEventsQueryTemplate : eventsQueryTemplate

                const query = template
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
                            operator: PropertyOperator.IsNot,
                            value: '',
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
                                    value: `(^|,)${escapeRegex(toolName)}(,|$)`,
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
                                    value: `(^|,)${escapeRegex(toolName)}(,|$)`,
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                })
            },
        ],
        buildAllToolsTrendQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): InsightVizNode => ({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || null,
                        date_to: dateFilter.dateTo || null,
                    },
                    filterTestAccounts: shouldFilterTestAccounts,
                    properties: [
                        ...propertyFilters,
                        {
                            key: '$ai_tools_called',
                            operator: PropertyOperator.IsNot,
                            value: '',
                            type: PropertyFilterType.Event,
                        },
                    ],
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_generation',
                        },
                    ],
                    breakdownFilter: {
                        breakdown:
                            "arrayJoin(arrayDistinct(splitByChar(',', ifNull(properties.$ai_tools_called, ''))))",
                        breakdown_type: 'hogql',
                        breakdown_limit: 10,
                    },
                },
            }),
        ],
        buildToolHeatmapQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): DataVisualizationNode => {
                const heatmapSql = `
-- Find pairwise tool co-occurrences across AI generations
WITH tool_arrays AS (
    -- Extract sorted, deduplicated tool lists from generations that called 2+ tools
    SELECT tools FROM (
        SELECT arraySort(arrayDistinct(splitByChar(',', ifNull(properties.$ai_tools_called, '')))) as tools
        FROM events
        WHERE event = '$ai_generation'
            AND properties.$ai_tools_called != ''
            AND {filters}
    )
    WHERE length(tools) > 1
),
tool_pairs AS (
    -- Build cross product of tools within each generation, excluding self-pairs
    SELECT
        arrayJoin(
            arrayFilter(
                p -> tupleElement(p, 1) != tupleElement(p, 2),
                arrayFlatten(arrayMap(a -> arrayMap(b -> tuple(a, b), tools), tools))
            )
        ) as pair
    FROM tool_arrays
)
SELECT
    tupleElement(pair, 1) as tool_a,
    tupleElement(pair, 2) as tool_b,
    count() as co_occurrences
FROM tool_pairs
GROUP BY tool_a, tool_b
ORDER BY co_occurrences DESC
LIMIT 200`

                return {
                    kind: NodeKind.DataVisualizationNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: heatmapSql,
                        filters: {
                            dateRange: {
                                date_from: dateFilter.dateFrom || null,
                                date_to: dateFilter.dateTo || null,
                            },
                            filterTestAccounts: shouldFilterTestAccounts,
                            properties: propertyFilters,
                        },
                    },
                    display: ChartDisplayType.TwoDimensionalHeatmap,
                    chartSettings: {
                        heatmap: {
                            xAxisColumn: 'tool_a',
                            yAxisColumn: 'tool_b',
                            valueColumn: 'co_occurrences',
                            xAxisLabel: 'Tool A',
                            yAxisLabel: 'Tool B',
                            gradientPreset: 'Blues',
                            gradientScaleMode: 'relative',
                        },
                    },
                }
            },
        ],
    }),
])
