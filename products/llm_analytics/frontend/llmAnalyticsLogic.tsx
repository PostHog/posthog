import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from 'lib/utils'
import { hasRecentAIEvents } from 'lib/utils/aiEventsUtils'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { isAnyPropertyFilters } from '~/queries/schema-guards'
import {
    DataTableNode,
    LLMTrace,
    NodeKind,
    ProductIntentContext,
    ProductKey,
    TraceQuery,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, Breadcrumb, PropertyFilterType } from '~/types'

import errorsQueryTemplate from '../backend/queries/errors.sql?raw'
import type { llmAnalyticsLogicType } from './llmAnalyticsLogicType'

export const LLM_ANALYTICS_DATA_COLLECTION_NODE_ID = 'llm-analytics-data'

const INITIAL_DASHBOARD_DATE_FROM = '-7d' as string | null
const INITIAL_EVENTS_DATE_FROM = '-1h' as string | null
const INITIAL_DATE_TO = null as string | null

export function getDefaultGenerationsColumns(showInputOutput: boolean): string[] {
    return [
        'uuid',
        'properties.$ai_trace_id',
        ...(showInputOutput ? ['properties.$ai_input[-1]', 'properties.$ai_output_choices'] : []),
        'person',
        "f'{properties.$ai_model}' -- Model",
        "if(properties.$ai_is_error = 'true', '❌', '') -- Error",
        "f'{round(toFloat(properties.$ai_latency), 2)} s' -- Latency",
        "f'{properties.$ai_input_tokens} → {properties.$ai_output_tokens} (∑ {toInt(properties.$ai_input_tokens) + toInt(properties.$ai_output_tokens)})' -- Token usage",
        "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Cost",
        'timestamp',
    ]
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

export const llmAnalyticsLogic = kea<llmAnalyticsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsLogic']),
    props({} as LLMAnalyticsLogicProps),
    key((props: LLMAnalyticsLogicProps) => props?.personId || 'llmAnalyticsScene'),
    connect(() => ({
        values: [
            sceneLogic,
            ['sceneKey'],
            groupsModel,
            ['groupsEnabled'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setShouldFilterSupportTraces: (shouldFilterSupportTraces: boolean) => ({ shouldFilterSupportTraces }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
        setGenerationsQuery: (query: DataTableNode) => ({ query }),
        setGenerationsColumns: (columns: string[]) => ({ columns }),
        setTracesQuery: (query: DataTableNode) => ({ query }),
        setSessionsSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        setUsersSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        setErrorsSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        setGenerationsSort: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
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

        shouldFilterSupportTraces: [
            false, // For impersonated users, default to NOT filtering (show support traces)
            {
                setShouldFilterSupportTraces: (_, { shouldFilterSupportTraces }) => shouldFilterSupportTraces,
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
            { column: 'traces', direction: 'DESC' } as { column: string; direction: 'ASC' | 'DESC' },
            {
                setErrorsSort: (_, { column, direction }) => ({ column, direction }),
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
        hasSentAiEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinition: async (): Promise<boolean> => {
                return hasRecentAIEvents()
            },
        },

        availableDashboards: [
            [] as Array<{ id: number; name: string; description: string }>,
            {
                loadLLMDashboards: async () => {
                    const response = await api.dashboards.list({
                        tags: 'llm-analytics',
                        creation_mode: 'unlisted',
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
                } else if (sceneKey === 'llmAnalyticsPrompts') {
                    return 'prompts'
                } else if (sceneKey === 'llmAnalyticsSettings') {
                    return 'settings'
                } else if (sceneKey === 'llmAnalyticsClusters') {
                    return 'clusters'
                }

                return 'dashboard'
            },
        ],

        tracesQuery: [
            (s) => [s.tracesQueryOverride, s.defaultTracesQuery],
            (override, defQuery) => override || defQuery,
        ],
        defaultTracesQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.shouldFilterSupportTraces,
                s.propertyFilters,
                (_, props) => props.personId,
                (_, props) => props.group,
                groupsModel.selectors.groupsTaxonomicTypes,
                featureFlagLogic.selectors.featureFlags,
                userLogic.selectors.user,
            ],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                shouldFilterSupportTraces: boolean,
                propertyFilters: AnyPropertyFilter[],
                personId: string | undefined,
                group: { groupKey: string; groupTypeIndex: number } | undefined,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[],
                featureFlags: { [flag: string]: boolean | string | undefined },
                user: { is_impersonated?: boolean } | null
            ): DataTableNode => {
                // For impersonated users (support agents), default to showing support traces
                // For regular users, always filter out support traces
                const filterSupportTraces = user?.is_impersonated ? shouldFilterSupportTraces : true

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.TracesQuery,
                        dateRange: {
                            date_from: dateFilter.dateFrom || undefined,
                            date_to: dateFilter.dateTo || undefined,
                        },
                        filterTestAccounts: shouldFilterTestAccounts ?? false,
                        filterSupportTraces,
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
                }
            },
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
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                errorsSort: { column: string; direction: 'ASC' | 'DESC' },
                groupsTaxonomicTypes: TaxonomicFilterGroupType[]
            ): DataTableNode => {
                // Use the shared query template
                // Simple placeholder replacement - no escaping needed
                const query = errorsQueryTemplate
                    .replace('__ORDER_BY__', errorsSort.column)
                    .replace('__ORDER_DIRECTION__', errorsSort.direction)

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
                        'error',
                        'traces',
                        'generations',
                        'spans',
                        'embeddings',
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
                }
            },
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
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                sessionsSort: { column: string; direction: 'ASC' | 'DESC' },
                groupsTaxonomicTypes: TaxonomicFilterGroupType[]
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
                    countIf(properties.$ai_is_error = 'true') as errors,
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
            [urls.llmAnalyticsSettings()]: () => {},
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
        actions.loadLLMDashboards()
    }),
])
