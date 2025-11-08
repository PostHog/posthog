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
        "if(notEmpty(properties.$ai_error) OR properties.$ai_is_error = 'true', '❌', '') -- Error",
        "f'{round(toFloat(properties.$ai_latency), 2)} s' -- Latency",
        "f'{properties.$ai_input_tokens} → {properties.$ai_output_tokens} (∑ {toInt(properties.$ai_input_tokens) + toInt(properties.$ai_output_tokens)})' -- Token usage",
        "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Cost",
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
    key((props: LLMAnalyticsLogicProps) => props?.personId || 'llmAnalyticsScene'),
    connect(() => ({
        values: [sceneLogic, ['sceneKey'], groupsModel, ['groupsEnabled'], featureFlagLogic, ['featureFlags']],
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
        setGenerationsQuery: (query: DataTableNode) => ({ query }),
        setGenerationsColumns: (columns: string[]) => ({ columns }),
        setTracesQuery: (query: DataTableNode) => ({ query }),
        setSessionsSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        setUsersSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        setErrorsSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        setGenerationsSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        refreshAllDashboardItems: true,
        setRefreshStatus: (tileId: string, loading?: boolean) => ({ tileId, loading }),
        toggleGenerationExpanded: (uuid: string, traceId: string) => ({ uuid, traceId }),
        setLoadedTrace: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        clearExpandedGenerations: true,
        toggleSessionExpanded: (sessionId: string) => ({ sessionId }),
        toggleTraceExpanded: (traceId: string) => ({ traceId }),
        loadSessionTraces: (sessionId: string) => ({ sessionId }),
        loadSessionTracesSuccess: (sessionId: string, traces: LLMTrace[]) => ({ sessionId, traces }),
        loadSessionTracesFailure: (sessionId: string, error: Error) => ({ sessionId, error }),
        loadFullTrace: (traceId: string) => ({ traceId }),
        loadFullTraceSuccess: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        loadFullTraceFailure: (traceId: string, error: Error) => ({ traceId, error }),
        loadLLMDashboards: true,
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

        generationsSort: [
            { column: 'timestamp', direction: 'DESC' } as { column: string; direction: 'ASC' | 'DESC' },
            {
                setGenerationsSort: (_, { column, direction }) => ({ column, direction }),
            },
        ],

        tracesQueryOverride: [
            null as DataTableNode | null,
            {
                setTracesQuery: (_, { query }) => query,
            },
        ],

        sessionsSort: [
            { column: 'last_seen', direction: 'DESC' } as { column: string; direction: 'ASC' | 'DESC' },
            {
                setSessionsSort: (_, { column, direction }) => ({ column, direction }),
            },
        ],

        usersSort: [
            { column: 'last_seen', direction: 'DESC' } as { column: string; direction: 'ASC' | 'DESC' },
            {
                setUsersSort: (_, { column, direction }) => ({ column, direction }),
            },
        ],

        errorsSort: [
            { column: 'generations', direction: 'DESC' } as { column: string; direction: 'ASC' | 'DESC' },
            {
                setErrorsSort: (_, { column, direction }) => ({ column, direction }),
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

        expandedSessionIds: [
            new Set<string>() as Set<string>,
            {
                toggleSessionExpanded: (state, { sessionId }) => {
                    const newSet = new Set(state)
                    if (newSet.has(sessionId)) {
                        newSet.delete(sessionId)
                    } else {
                        newSet.add(sessionId)
                    }
                    return newSet
                },
                setDates: () => new Set<string>(),
                setPropertyFilters: () => new Set<string>(),
                setShouldFilterTestAccounts: () => new Set<string>(),
            },
        ],

        expandedTraceIds: [
            new Set<string>() as Set<string>,
            {
                toggleTraceExpanded: (state, { traceId }) => {
                    const newSet = new Set(state)
                    if (newSet.has(traceId)) {
                        newSet.delete(traceId)
                    } else {
                        newSet.add(traceId)
                    }
                    return newSet
                },
                setDates: () => new Set<string>(),
                setPropertyFilters: () => new Set<string>(),
                setShouldFilterTestAccounts: () => new Set<string>(),
            },
        ],

        sessionTraces: [
            {} as Record<string, LLMTrace[]>,
            {
                loadSessionTracesSuccess: (state, { sessionId, traces }) => ({
                    ...state,
                    [sessionId]: traces,
                }),
                setDates: () => ({}),
                setPropertyFilters: () => ({}),
                setShouldFilterTestAccounts: () => ({}),
            },
        ],

        fullTraces: [
            {} as Record<string, LLMTrace>,
            {
                loadFullTraceSuccess: (state, { traceId, trace }) => ({
                    ...state,
                    [traceId]: trace,
                }),
                setDates: () => ({}),
                setPropertyFilters: () => ({}),
                setShouldFilterTestAccounts: () => ({}),
            },
        ],

        loadingSessionTraces: [
            new Set<string>() as Set<string>,
            {
                loadSessionTraces: (state, { sessionId }) => new Set(state).add(sessionId),
                loadSessionTracesSuccess: (state, { sessionId }) => {
                    const newSet = new Set(state)
                    newSet.delete(sessionId)
                    return newSet
                },
                loadSessionTracesFailure: (state, { sessionId }) => {
                    const newSet = new Set(state)
                    newSet.delete(sessionId)
                    return newSet
                },
            },
        ],

        loadingFullTraces: [
            new Set<string>() as Set<string>,
            {
                loadFullTrace: (state, { traceId }) => new Set(state).add(traceId),
                loadFullTraceSuccess: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.delete(traceId)
                    return newSet
                },
                loadFullTraceFailure: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.delete(traceId)
                    return newSet
                },
            },
        ],

        selectedDashboardId: [
            null as number | null,
            { persist: true, prefix: 'llma_' },
            {
                loadLLMDashboardsSuccess: (state, { availableDashboards }) => {
                    // If no dashboards available, clear selection
                    if (availableDashboards.length === 0) {
                        return null
                    }

                    // If currently selected dashboard still exists in list, keep it
                    if (state && availableDashboards.some((d) => d.id === state)) {
                        return state
                    }

                    // Otherwise, select first available dashboard (new or after deletion)
                    return availableDashboards[0].id
                },
            },
        ],
    }),

    loaders(() => ({
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

        availableDashboards: [
            [] as Array<{ id: number; name: string; description: string }>,
            {
                loadLLMDashboards: async () => {
                    const response = await api.dashboards.list({
                        tags: 'llm-analytics',
                    })
                    const dashboards = response.results || []
                    return dashboards.map((d) => ({
                        id: d.id,
                        name: d.name,
                        description: d.description || '',
                    }))
                },
            },
        ],
    })),

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

        toggleSessionExpanded: async ({ sessionId }) => {
            if (
                values.expandedSessionIds.has(sessionId) &&
                !values.sessionTraces[sessionId] &&
                !values.loadingSessionTraces.has(sessionId)
            ) {
                actions.loadSessionTraces(sessionId)
            }
        },

        loadSessionTraces: async ({ sessionId }) => {
            const dateFrom = values.dateFilter.dateFrom || undefined
            const dateTo = values.dateFilter.dateTo || undefined

            const tracesQuerySource: import('~/queries/schema/schema-general').TracesQuery = {
                kind: NodeKind.TracesQuery,
                dateRange: {
                    date_from: dateFrom,
                    date_to: dateTo,
                },
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$ai_session_id',
                        operator: 'exact' as any,
                        value: sessionId,
                    },
                ],
            }

            try {
                const response = await api.query(tracesQuerySource)
                if (response.results) {
                    actions.loadSessionTracesSuccess(sessionId, response.results)
                }
            } catch (error) {
                console.error('Error loading traces for session:', error)
                actions.loadSessionTracesFailure(sessionId, error as Error)
            }
        },

        toggleTraceExpanded: async ({ traceId }) => {
            if (
                values.expandedTraceIds.has(traceId) &&
                !values.fullTraces[traceId] &&
                !values.loadingFullTraces.has(traceId)
            ) {
                actions.loadFullTrace(traceId)
            }
        },

        loadFullTrace: async ({ traceId }) => {
            const dateFrom = values.dateFilter.dateFrom || undefined
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
                if (response.results && response.results[0]) {
                    actions.loadFullTraceSuccess(traceId, response.results[0])
                }
            } catch (error) {
                console.error('Error loading full trace:', error)
                actions.loadFullTraceFailure(traceId, error as Error)
            }
        },

        loadLLMDashboardsSuccess: async ({ availableDashboards }, breakpoint) => {
            if (availableDashboards.length === 0) {
                try {
                    await api.dashboards.createUnlistedDashboard('llm-analytics')
                    await breakpoint(100)
                    actions.loadLLMDashboards()
                } catch (error: any) {
                    if (error.status === 409) {
                        await breakpoint(100)
                        actions.loadLLMDashboards()
                    } else {
                        console.error('Failed to create default LLM Analytics dashboard:', error)
                    }
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
                } else if (sceneKey === 'llmAnalyticsErrors') {
                    return 'errors'
                } else if (sceneKey === 'llmAnalyticsSessions') {
                    return 'sessions'
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

        // IMPORTANT: Keep these hardcoded tiles in sync with backend template in
        // products/llm_analytics/backend/dashboard_templates.py:4-319 until full migration to customizable dashboard.
        //
        // Used when LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD feature flag is OFF.
        // When feature flag is ON, dashboard is loaded from backend template instead.
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
                    title: 'Cost',
                    description: 'Total cost of all generations',
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
                    title: 'Cost per user',
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
                    title: 'Cost by model',
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
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                personId: string | undefined,
                group: { groupKey: string; groupTypeIndex: number } | undefined,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[],
                featureFlags: { [flag: string]: boolean | string | undefined }
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
                    'errors',
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
                s.generationsSort,
                groupsModel.selectors.groupsTaxonomicTypes,
                featureFlagLogic.selectors.featureFlags,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                generationsColumns,
                generationsSort,
                groupsTaxonomicTypes,
                featureFlags
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select:
                        generationsColumns ||
                        getDefaultGenerationsColumns(!!featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT]),
                    orderBy: [`${generationsSort.column} ${generationsSort.direction}`],
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
                s.usersSort,
                groupsModel.selectors.groupsTaxonomicTypes,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                usersSort,
                groupsTaxonomicTypes
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                SELECT
                    argMax(user_tuple, timestamp) as user,
                    countDistinctIf(ai_trace_id, notEmpty(ai_trace_id)) as traces,
                    count() as generations,
                    countIf(notEmpty(ai_error) OR ai_is_error = 'true') as errors,
                    round(sum(toFloat(ai_total_cost_usd)), 4) as total_cost,
                    min(timestamp) as first_seen,
                    max(timestamp) as last_seen
                FROM (
                    SELECT
                        distinct_id,
                        timestamp,
                        JSONExtractRaw(properties, '$ai_trace_id') as ai_trace_id,
                        JSONExtractRaw(properties, '$ai_total_cost_usd') as ai_total_cost_usd,
                        JSONExtractRaw(properties, '$ai_error') as ai_error,
                        JSONExtractString(properties, '$ai_is_error') as ai_is_error,
                        tuple(
                            distinct_id,
                            person.created_at,
                            person.properties
                        ) as user_tuple
                    FROM events
                    WHERE event = '$ai_generation' AND {filters}
                )
                GROUP BY distinct_id
                ORDER BY ${usersSort.column} ${usersSort.direction}
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
                columns: ['user', 'traces', 'generations', 'errors', 'total_cost', 'first_seen', 'last_seen'],
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
            }),
        ],
        errorsQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.errorsSort,
                groupsModel.selectors.groupsTaxonomicTypes,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                errorsSort,
                groupsTaxonomicTypes
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                -- Error normalization pipeline: extract -> normalize IDs -> normalize UUIDs -> normalize timestamps -> normalize paths -> normalize response IDs -> normalize tool call IDs -> normalize token counts -> normalize all remaining numbers
                -- This multi-step CTE approach makes it easy to understand and maintain each normalization step

                WITH extracted_errors AS (
                    -- Step 1: Extract error messages from various JSON structures in $ai_error
                    -- Different SDKs/libraries format errors differently, so we try multiple paths
                    SELECT
                        distinct_id,
                        timestamp,
                        JSONExtractRaw(properties, '$ai_trace_id') as ai_trace_id,
                        JSONExtractRaw(properties, '$ai_session_id') as ai_session_id,
                        CASE
                            -- Try: { error: { message: "..." } } (nested error object with message)
                            WHEN notEmpty(JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message'))
                                THEN JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message')
                            -- Try: { message: "..." } (direct message property)
                            WHEN notEmpty(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message'))
                                THEN JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message')
                            -- Try: { error: "..." } (error as string property)
                            WHEN notEmpty(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'))
                                THEN JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error')
                            -- Fallback: use the raw string value
                            ELSE JSONExtractString(properties, '$ai_error')
                        END as raw_error
                    FROM events
                    WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding')
                        AND (notEmpty(JSONExtractString(properties, '$ai_error')) OR JSONExtractString(properties, '$ai_is_error') = 'true')
                        AND {filters}
                ),
                ids_normalized AS (
                    -- Step 2: Normalize large numeric IDs (9+ digits)
                    -- Replaces timestamps, project IDs, and other long numbers with <ID>
                    -- Example: "Error 1234567890" -> "Error <ID>"
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(raw_error, '[0-9]{9,}', '<ID>') as error_text
                    FROM extracted_errors
                ),
                uuids_normalized AS (
                    -- Step 3: Normalize UUIDs and request IDs
                    -- Replaces request IDs (req_xxx) and standard UUIDs with <ID>
                    -- Example: "req_abc123" -> "<ID>", "550e8400-e29b-41d4-a716-446655440000" -> "<ID>"
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(error_text, '(req_[a-zA-Z0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', '<ID>') as error_text
                    FROM ids_normalized
                ),
                timestamps_normalized AS (
                    -- Step 4: Normalize ISO timestamps
                    -- Replaces ISO 8601 timestamps with <TIMESTAMP> to group errors that differ only by time
                    -- Example: "2025-11-08T14:25:51.767Z" -> "<TIMESTAMP>"
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(error_text, '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]+Z?', '<TIMESTAMP>') as error_text
                    FROM uuids_normalized
                ),
                paths_normalized AS (
                    -- Step 5: Normalize cloud resource paths
                    -- Replaces Google Cloud project paths with a generic placeholder
                    -- Example: "projects/123/locations/us-west2/publishers/google/models/gemini-pro" -> "projects/<PATH>"
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(error_text, 'projects/[0-9a-z-]+(/[a-z]+/[0-9a-z-]+)+', 'projects/<PATH>') as error_text
                    FROM timestamps_normalized
                ),
                response_ids_normalized AS (
                    -- Step 6: Normalize responseId fields in error payloads
                    -- Many LLM providers include unique response IDs in error messages
                    -- Example: "responseId":"abc123xyz" -> "responseId":"<RESPONSE_ID>" or responseId:abc123xyz -> responseId:<RESPONSE_ID>
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(error_text, '"responseId":"[a-zA-Z0-9_-]+"', '"responseId":"<RESPONSE_ID>"') as error_text
                    FROM paths_normalized
                ),
                tool_call_ids_normalized AS (
                    -- Step 7: Normalize tool_call_id values
                    -- Tool calling frameworks include unique tool call IDs in error messages
                    -- Example: "tool_call_id='toolu_01LCbNr67BxhgUH6gndPCELW'" -> "tool_call_id='<TOOL_CALL_ID>'"
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(error_text, 'tool_call_id=[''"][a-zA-Z0-9_-]+[''"]', 'tool_call_id=''<TOOL_CALL_ID>''') as error_text
                    FROM response_ids_normalized
                ),
                token_counts_normalized AS (
                    -- Step 8: Normalize token count values
                    -- Token counts are metadata, not part of error identity
                    -- Example: "tokenCount":7125 -> "tokenCount":<TOKEN_COUNT>
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(error_text, '"tokenCount":[0-9]+', '"tokenCount":<TOKEN_COUNT>') as error_text
                    FROM tool_call_ids_normalized
                ),
                all_numbers_normalized AS (
                    -- Step 9: Normalize all remaining numbers as final fallback
                    -- Catches any dynamic numbers not covered by specific patterns above (ports, sizes, counts, etc.)
                    -- Applied last so specific normalizations take precedence
                    -- Example: "port 8080" -> "port <N>", "size 1024" -> "size <N>"
                    SELECT
                        distinct_id,
                        timestamp,
                        ai_trace_id,
                        ai_session_id,
                        replaceRegexpAll(error_text, '[0-9]+', '<N>') as normalized_error
                    FROM token_counts_normalized
                )
                -- Final aggregation: group by normalized error and calculate metrics
                SELECT
                    normalized_error as error,
                    countDistinctIf(ai_trace_id, notEmpty(ai_trace_id)) as traces,
                    count() as generations,
                    countDistinctIf(ai_session_id, notEmpty(ai_session_id)) as sessions,
                    uniq(distinct_id) as users,
                    uniq(toDate(timestamp)) as days_seen,
                    min(timestamp) as first_seen,
                    max(timestamp) as last_seen
                FROM all_numbers_normalized
                GROUP BY normalized_error
                ORDER BY ${errorsSort.column} ${errorsSort.direction}
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
                columns: [
                    'error',
                    'traces',
                    'generations',
                    'sessions',
                    'users',
                    'days_seen',
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
            }),
        ],
        sessionsQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.sessionsSort,
                groupsModel.selectors.groupsTaxonomicTypes,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                sessionsSort,
                groupsTaxonomicTypes
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                SELECT
                    properties.$ai_session_id as session_id,
                    countDistinctIf(properties.$ai_trace_id, isNotNull(properties.$ai_trace_id)) as traces,
                    countIf(event = '$ai_span') as spans,
                    countIf(event = '$ai_generation') as generations,
                    countIf(event = '$ai_embedding') as embeddings,
                    countIf(isNotNull(properties.$ai_error) OR properties.$ai_is_error = 'true') as errors,
                    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) as total_cost,
                    round(sum(toFloat(properties.$ai_latency)), 2) as total_latency,
                    min(timestamp) as first_seen,
                    max(timestamp) as last_seen
                FROM events
                WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace')
                    AND isNotNull(properties.$ai_session_id)
                    AND properties.$ai_session_id != ''
                    AND {filters}
                GROUP BY properties.$ai_session_id
                ORDER BY ${sessionsSort.column} ${sessionsSort.direction}
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
                columns: [
                    'session_id',
                    'traces',
                    'spans',
                    'generations',
                    'embeddings',
                    'errors',
                    'total_cost',
                    'total_latency',
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
            [urls.llmAnalyticsErrors()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmAnalyticsSessions()]: (_, searchParams) => applySearchParams(searchParams),
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

    afterMount(({ actions, values }) => {
        actions.loadAIEventDefinition()

        if (values.featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD]) {
            actions.loadLLMDashboards()
        }
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
