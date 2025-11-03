import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from 'lib/utils'
import { isDefinitionStale } from 'lib/utils/definitions'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { isAnyPropertyFilters } from '~/queries/schema-guards'
import { DataTableNode, LLMTrace, NodeKind, TraceQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import {
    AnyPropertyFilter,
    BaseMathType,
    Breadcrumb,
    ChartDisplayType,
    EventDefinitionType,
    HogQLMathType,
    InsightShortId,
    ProductKey,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import type { llmAnalyticsLogicType } from './llmAnalyticsLogicType'

export const LLM_ANALYTICS_DATA_COLLECTION_NODE_ID = 'llm-analytics-data'

const INITIAL_DASHBOARD_DATE_FROM = '-7d' as string | null
const INITIAL_EVENTS_DATE_FROM = '-1d' as string | null
const INITIAL_DATE_TO = null as string | null

export function getDefaultGenerationsColumns(showInputOutput: boolean): string[] {
    return [
        'uuid',
        'properties.$ai_trace_id',
        ...(showInputOutput ? ['properties.$ai_input[-1]', 'properties.$ai_output_choices'] : []),
        'person',
        "f'{properties.$ai_model}' -- Model",
        "f'{round(toFloat(properties.$ai_latency), 2)} s' -- Latency",
        "f'{properties.$ai_input_tokens} → {properties.$ai_output_tokens} (∑ {toInt(properties.$ai_input_tokens) + toInt(properties.$ai_output_tokens)})' -- Token usage",
        "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Total cost",
        'timestamp',
    ]
}

export interface QueryTile {
    title: string
    description?: string
    query: TrendsQuery
    context?: QueryContext
    layout?: {
        className?: string
    }
}

export interface LLMAnalyticsLogicProps {
    logicKey?: string
    tabId?: string
    personId?: string
    group?: {
        groupKey: string
        groupTypeIndex: number
    }
}

/**
 * Helper function to get date range for a specific day.
 * @param day - The day string from the chart (e.g., "2024-01-15")
 * @returns Object with date_from and date_to formatted strings
 */
function getDayDateRange(day: string): { date_from: string; date_to: string } {
    const dayStart = dayjs(day).startOf('day')
    return {
        date_from: dayStart.format('YYYY-MM-DD[T]HH:mm:ss'),
        date_to: dayStart.add(1, 'day').subtract(1, 'second').format('YYYY-MM-DD[T]HH:mm:ss'),
    }
}

export const llmAnalyticsLogic = kea<llmAnalyticsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsLogic']),
    props({} as LLMAnalyticsLogicProps),
    key(({ logicKey }: LLMAnalyticsLogicProps) => logicKey || 'llmAnalyticsScene'),
    connect(() => ({
        values: [sceneLogic, ['sceneKey'], groupsModel, ['groupsEnabled']],
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setDashboardDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
        setGenerationsQuery: (query: DataTableNode) => ({ query }),
        setGenerationsColumns: (columns: string[]) => ({ columns }),
        setTracesQuery: (query: DataTableNode) => ({ query }),
        refreshAllDashboardItems: true,
        setRefreshStatus: (tileId: string, loading?: boolean) => ({ tileId, loading }),
        toggleGenerationExpanded: (uuid: string, traceId: string) => ({ uuid, traceId }),
        setLoadedTrace: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        clearExpandedGenerations: true,
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_EVENTS_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],

        dashboardDateFilter: [
            {
                dateFrom: INITIAL_DASHBOARD_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],

        shouldFilterTestAccounts: [
            false,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],

        propertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { propertyFilters }) => propertyFilters,
            },
        ],

        generationsQueryOverride: [
            null as DataTableNode | null,
            {
                setGenerationsQuery: (_, { query }) => query,
            },
        ],

        generationsColumns: [
            null as string[] | null,
            { persist: true },
            {
                setGenerationsColumns: (_, { columns }) => columns,
            },
        ],

        tracesQueryOverride: [
            null as DataTableNode | null,
            {
                setTracesQuery: (_, { query }) => query,
            },
        ],

        refreshStatus: [
            {} as Record<string, { loading?: boolean; timer?: Date }>,
            {
                setRefreshStatus: (state, { tileId, loading }) => ({
                    ...state,
                    [tileId]: loading ? { loading: true, timer: new Date() } : state[tileId],
                }),
                refreshAllDashboardItems: () => ({}),
            },
        ],

        newestRefreshed: [
            null as Date | null,
            {
                setRefreshStatus: (state, { loading }) => (!loading ? new Date() : state),
            },
        ],

        expandedGenerationIds: [
            new Set<string>() as Set<string>,
            {
                toggleGenerationExpanded: (state, { uuid }) => {
                    const newSet = new Set(state)
                    if (newSet.has(uuid)) {
                        newSet.delete(uuid)
                    } else {
                        newSet.add(uuid)
                    }
                    return newSet
                },
                clearExpandedGenerations: () => new Set<string>(),
                setDates: () => new Set<string>(),
                setPropertyFilters: () => new Set<string>(),
                setShouldFilterTestAccounts: () => new Set<string>(),
            },
        ],

        loadedTraces: [
            {} as Record<string, LLMTrace>,
            {
                setLoadedTrace: (state, { traceId, trace }) => ({
                    ...state,
                    [traceId]: trace,
                }),
                clearExpandedGenerations: () => ({}),
                setDates: () => ({}),
                setPropertyFilters: () => ({}),
                setShouldFilterTestAccounts: () => ({}),
            },
        ],
    }),

    loaders({
        hasSentAiGenerationEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinition: async (): Promise<boolean> => {
                const aiGenerationDefinition = await api.eventDefinitions.list({
                    event_type: EventDefinitionType.Event,
                    search: '$ai_generation',
                })

                // no need to worry about pagination here, event names beginning with $ are reserved, and we're not
                // going to add enough reserved event names that match this search term to cause problems
                const definition = aiGenerationDefinition.results.find((r) => r.name === '$ai_generation')
                if (definition && !isDefinitionStale(definition)) {
                    return true
                }
                return false
            },
        },
    }),

    listeners(({ actions, values }) => ({
        toggleGenerationExpanded: async ({ uuid, traceId }) => {
            // Only load if expanding and not already loaded
            if (values.expandedGenerationIds.has(uuid) && !values.loadedTraces[traceId]) {
                // Build TraceQuery with date range from current filters
                const dateFrom = values.dateFilter.dateFrom || '-7d'
                const dateTo = values.dateFilter.dateTo || undefined

                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                    dateRange: {
                        date_from: dateFrom,
                        date_to: dateTo,
                    },
                }

                try {
                    const response = await api.query(traceQuery)
                    if (response.results && response.results.length > 0) {
                        actions.setLoadedTrace(traceId, response.results[0])
                    }
                } catch (error) {
                    console.error('Failed to load trace:', error)
                }
            }
        },
    })),

    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey) => {
                if (sceneKey === 'llmAnalyticsGenerations') {
                    return 'generations'
                } else if (sceneKey === 'llmAnalyticsTraces') {
                    return 'traces'
                } else if (sceneKey === 'llmAnalyticsUsers') {
                    return 'users'
                } else if (sceneKey === 'llmAnalyticsPlayground') {
                    return 'playground'
                } else if (sceneKey === 'llmAnalyticsDatasets') {
                    return 'datasets'
                } else if (sceneKey === 'llmAnalyticsEvaluations') {
                    return 'evaluations'
                }
                return 'dashboard'
            },
        ],

        tiles: [
            (s) => [s.dashboardDateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (dashboardDateFilter, shouldFilterTestAccounts, propertyFilters): QueryTile[] => [
                {
                    title: 'Traces',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: HogQLMathType.HogQL,
                                math_hogql: 'COUNT(DISTINCT properties.$ai_trace_id)',
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        insightProps: {
                            dashboardItemId: `new-traces-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                // NOTE: This assumes the chart is day-by-day
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsTraces(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Generative AI users',
                    description: 'To count users, set `distinct_id` in LLM tracking.',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters.concat({
                            type: PropertyFilterType.HogQL,
                            key: 'distinct_id != properties.$ai_trace_id',
                        }),
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        insightProps: {
                            dashboardItemId: `new-generations-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)

                                router.actions.push(urls.llmAnalyticsUsers(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Total cost (USD)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                        ],
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 4,
                            display: ChartDisplayType.BoldNumber,
                        },
                        dateRange: {
                            date_from: dashboardDateFilter.dateFrom,
                            date_to: dashboardDateFilter.dateTo,
                            explicitDate: true,
                        },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'traces',
                        onDataPointClick: () => {
                            router.actions.push(urls.llmAnalyticsTraces(), {
                                ...router.values.searchParams,
                                // Use same date range as dashboard to ensure we'll see the same data after click
                                date_from: dashboardDateFilter.dateFrom,
                                date_to: dashboardDateFilter.dateTo,
                            })
                        },
                    },
                },
                {
                    title: 'Cost per user (USD)',
                    description: "Average cost for each generative AI user active in the data point's period.",
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        trendsFilter: {
                            formula: 'A / B',
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                        },
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters.concat({
                            type: PropertyFilterType.HogQL,
                            key: 'distinct_id != properties.$ai_trace_id',
                        }),
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        insightProps: {
                            dashboardItemId: `new-cost-per-user-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)

                                router.actions.push(urls.llmAnalyticsUsers(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Cost by model (USD)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                        ],
                        breakdownFilter: {
                            breakdown_type: 'event',
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                            display: ChartDisplayType.ActionsBarValue,
                            showValuesOnSeries: true,
                        },
                        dateRange: {
                            date_from: dashboardDateFilter.dateFrom,
                            date_to: dashboardDateFilter.dateTo,
                            explicitDate: true,
                        },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'traces',
                        onDataPointClick: ({ breakdown }) => {
                            router.actions.push(urls.llmAnalyticsTraces(), {
                                ...router.values.searchParams,
                                // Use same date range as dashboard to ensure we'll see the same data after click
                                date_from: dashboardDateFilter.dateFrom,
                                date_to: dashboardDateFilter.dateTo,
                                filters: [
                                    ...(router.values.searchParams.filters || []),
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$ai_model',
                                        operator: PropertyOperator.Exact,
                                        value: breakdown as string,
                                    },
                                ],
                            })
                        },
                    },
                },
                {
                    title: 'Generation calls',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'generations',
                        insightProps: {
                            dashboardItemId: `new-generation-calls-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsGenerations(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                })
                            }
                        },
                    },
                },
                {
                    title: 'AI Errors',
                    description: 'Failed AI generation calls',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters.concat({
                            type: PropertyFilterType.Event,
                            key: '$ai_is_error',
                            operator: PropertyOperator.Exact,
                            value: true,
                        }),
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'errors',
                        insightProps: {
                            dashboardItemId: `new-ai-errors-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsGenerations(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                    filters: [
                                        ...(router.values.searchParams.filters || []),
                                        {
                                            type: PropertyFilterType.Event,
                                            key: '$ai_is_error',
                                            operator: PropertyOperator.Exact,
                                            value: true,
                                        },
                                    ] as AnyPropertyFilter[],
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Generation latency by model (median)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Median,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_latency',
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPostfix: ' s',
                            decimalPlaces: 2,
                        },
                        dateRange: { date_from: dashboardDateFilter.dateFrom, date_to: dashboardDateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'generations',
                        insightProps: {
                            dashboardItemId: `new-generation-latency-by-model-query`,
                        },
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                const { date_from, date_to } = getDayDateRange(series.day)
                                router.actions.push(urls.llmAnalyticsGenerations(), {
                                    ...router.values.searchParams,
                                    date_from,
                                    date_to,
                                    filters: [
                                        ...(router.values.searchParams.filters || []),
                                        {
                                            type: PropertyFilterType.Event,
                                            key: '$ai_model',
                                            operator: PropertyOperator.Exact,
                                            value: series.breakdown as string,
                                        },
                                    ] as AnyPropertyFilter[],
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Generations by HTTP status',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_http_status',
                        },
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBarValue,
                        },
                        dateRange: {
                            date_from: dashboardDateFilter.dateFrom,
                            date_to: dashboardDateFilter.dateTo,
                            explicitDate: true,
                        },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'generations',
                        onDataPointClick: (series) => {
                            router.actions.push(urls.llmAnalyticsGenerations(), {
                                ...router.values.searchParams,
                                // Use same date range as dashboard to ensure we'll see the same data after click
                                date_from: dashboardDateFilter.dateFrom,
                                date_to: dashboardDateFilter.dateTo,
                                filters: [
                                    ...(router.values.searchParams.filters || []),
                                    {
                                        type: PropertyFilterType.Event,
                                        key: '$ai_http_status',
                                        operator: PropertyOperator.Exact,
                                        value: series.breakdown as string,
                                    },
                                ] as AnyPropertyFilter[],
                            })
                        },
                    },
                },
            ],
        ],

        tracesQuery: [
            (s) => [s.tracesQueryOverride, s.defaultTracesQuery],
            (override, defQuery) => override || defQuery,
        ],
        defaultTracesQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                (_, props) => props.personId,
                (_, props) => props.group,
                groupsModel.selectors.groupsTaxonomicTypes,
                featureFlagLogic.selectors.featureFlags,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                personId,
                group,
                groupsTaxonomicTypes,
                featureFlags
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.TracesQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || undefined,
                        date_to: dateFilter.dateTo || undefined,
                    },
                    filterTestAccounts: shouldFilterTestAccounts ?? false,
                    properties: propertyFilters,
                    personId: personId ?? undefined,
                    groupKey: group?.groupKey,
                    groupTypeIndex: group?.groupTypeIndex,
                },
                columns: [
                    'id',
                    'traceName',
                    ...(featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT]
                        ? ['inputState', 'outputState']
                        : []),
                    'person',
                    'totalLatency',
                    'usage',
                    'totalCost',
                    'timestamp',
                ],
                showDateRange: true,
                showReload: true,
                showSearch: true,
                showTestAccountFilters: true,
                showExport: true,
                showOpenEditorButton: false,
                showColumnConfigurator: false,
                showPropertyFilter: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
            }),
        ],
        generationsQuery: [
            (s) => [s.generationsQueryOverride, s.defaultGenerationsQuery],
            (override, defQuery) => override || defQuery,
        ],
        defaultGenerationsQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.generationsColumns,
                groupsModel.selectors.groupsTaxonomicTypes,
                featureFlagLogic.selectors.featureFlags,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                generationsColumns,
                groupsTaxonomicTypes,
                featureFlags
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select:
                        generationsColumns ||
                        getDefaultGenerationsColumns(!!featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT]),
                    orderBy: ['timestamp DESC'],
                    after: dateFilter.dateFrom || undefined,
                    before: dateFilter.dateTo || undefined,
                    filterTestAccounts: shouldFilterTestAccounts,
                    event: '$ai_generation',
                    properties: propertyFilters,
                },
                showDateRange: true,
                showReload: true,
                showSearch: true,
                showTestAccountFilters: true,
                showColumnConfigurator: true,
                showPropertyFilter: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
                showExport: true,
                showActions: false,
            }),
        ],
        usersQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                groupsModel.selectors.groupsTaxonomicTypes,
            ],
            (dateFilter, shouldFilterTestAccounts, propertyFilters, groupsTaxonomicTypes): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                SELECT
                    argMax(user_tuple, timestamp) as user,
                    countDistinctIf(ai_trace_id, notEmpty(ai_trace_id)) as traces,
                    count() as generations,
                    round(sum(toFloat(ai_total_cost_usd)), 4) as total_cost,
                    min(timestamp) as first_seen,
                    max(timestamp) as last_seen
                FROM (
                    SELECT
                        distinct_id,
                        timestamp,
                        JSONExtractRaw(properties, '$ai_trace_id') as ai_trace_id,
                        JSONExtractRaw(properties, '$ai_total_cost_usd') as ai_total_cost_usd,
                        tuple(
                            distinct_id,
                            person.created_at,
                            person.properties
                        ) as user_tuple
                    FROM events
                    WHERE event = '$ai_generation' AND {filters}
                )
                GROUP BY distinct_id
                ORDER BY total_cost DESC
                LIMIT 50
                    `,
                    filters: {
                        dateRange: {
                            date_from: dateFilter.dateFrom || null,
                            date_to: dateFilter.dateTo || null,
                        },
                        filterTestAccounts: shouldFilterTestAccounts,
                        properties: propertyFilters,
                    },
                },
                columns: ['user', 'traces', 'generations', 'total_cost', 'first_seen', 'last_seen'],
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
            }),
        ],
        isRefreshing: [
            (s) => [s.refreshStatus],
            (refreshStatus) => Object.values(refreshStatus).some((status) => status.loading),
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: 'llm_analytics',
                        name: 'LLM Analytics',
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
    }),

    tabAwareUrlToAction(({ actions, values }) => {
        function applySearchParams({ filters, date_from, date_to, filter_test_accounts }: Record<string, any>): void {
            const parsedFilters = isAnyPropertyFilters(filters) ? filters : []
            if (!objectsEqual(parsedFilters, values.propertyFilters)) {
                actions.setPropertyFilters(parsedFilters)
            }

            if (
                (date_from || INITIAL_EVENTS_DATE_FROM) !== values.dateFilter.dateFrom ||
                (date_to || INITIAL_DATE_TO) !== values.dateFilter.dateTo
            ) {
                actions.setDates(date_from || INITIAL_EVENTS_DATE_FROM, date_to || INITIAL_DATE_TO)
            }

            const filterTestAccountsValue = [true, 'true', 1, '1'].includes(filter_test_accounts)
            if (filterTestAccountsValue !== values.shouldFilterTestAccounts) {
                actions.setShouldFilterTestAccounts(filterTestAccountsValue)
            }
        }

        return {
            [urls.llmAnalyticsDashboard()]: (_, searchParams) => {
                applySearchParams(searchParams)
                actions.addProductIntent({
                    product_type: ProductKey.LLM_ANALYTICS,
                    intent_context: ProductIntentContext.LLM_ANALYTICS_VIEWED,
                })
            },
            [urls.llmAnalyticsGenerations()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsTraces()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsUsers()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsPlayground()]: (_, searchParams) => applySearchParams(searchParams),
        }
    }),

    tabAwareActionToUrl(() => ({
        setPropertyFilters: ({ propertyFilters }) => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                filters: propertyFilters.length > 0 ? propertyFilters : undefined,
            },
        ],
        setDates: ({ dateFrom, dateTo }) => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                date_from: dateFrom === INITIAL_EVENTS_DATE_FROM ? undefined : dateFrom || undefined,
                date_to: dateTo || undefined,
            },
        ],
        setShouldFilterTestAccounts: ({ shouldFilterTestAccounts }) => [
            router.values.location.pathname,
            {
                ...router.values.searchParams,
                filter_test_accounts: shouldFilterTestAccounts ? 'true' : undefined,
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadAIEventDefinition()
    }),

    listeners(({ actions, values }) => ({
        refreshAllDashboardItems: async () => {
            // Set loading state for all tiles
            values.tiles.forEach((_, index) => {
                actions.setRefreshStatus(`tile-${index}`, true)
            })

            try {
                // Refresh all tiles in parallel
                values.tiles.map((tile, index) => {
                    const insightProps = {
                        dashboardItemId: tile.context?.insightProps?.dashboardItemId as InsightShortId,
                    }
                    const mountedInsightDataLogic = insightDataLogic.findMounted(insightProps)
                    if (mountedInsightDataLogic) {
                        mountedInsightDataLogic.actions.loadData('force_blocking')
                    }
                    actions.setRefreshStatus(`tile-${index}`, false)
                })
            } catch (error) {
                console.error('Error refreshing dashboard items:', error)
                // Clear loading states on error
                values.tiles.forEach((_, index) => {
                    actions.setRefreshStatus(`tile-${index}`, false)
                })
            }
        },
    })),
])
