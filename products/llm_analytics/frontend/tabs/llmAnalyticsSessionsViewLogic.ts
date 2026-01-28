import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, LLMTrace, NodeKind, TraceQuery, TracesQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { SortDirection, SortState, llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmAnalyticsSessionsViewLogicType } from './llmAnalyticsSessionsViewLogicType'

export const llmAnalyticsSessionsViewLogic = kea<llmAnalyticsSessionsViewLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tabs', 'llmAnalyticsSessionsViewLogic']),
    connect({
        values: [
            llmAnalyticsSharedLogic,
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
        actions: [llmAnalyticsSharedLogic, ['setDates', 'setPropertyFilters', 'setShouldFilterTestAccounts']],
    }),

    actions({
        setSessionsSort: (column: string, direction: SortDirection) => ({ column, direction }),
        toggleSessionExpanded: (sessionId: string) => ({ sessionId }),
        toggleTraceExpanded: (traceId: string) => ({ traceId }),
        toggleGenerationExpanded: (uuid: string, traceId: string) => ({ uuid, traceId }),
        loadSessionTraces: (sessionId: string) => ({ sessionId }),
        loadSessionTracesSuccess: (sessionId: string, traces: LLMTrace[]) => ({ sessionId, traces }),
        loadSessionTracesFailure: (sessionId: string, error: Error) => ({ sessionId, error }),
        loadFullTrace: (traceId: string) => ({ traceId }),
        loadFullTraceSuccess: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        loadFullTraceFailure: (traceId: string, error: Error) => ({ traceId, error }),
    }),

    reducers({
        sessionsSort: [
            { column: 'last_seen', direction: 'DESC' } as SortState,
            {
                setSessionsSort: (_, { column, direction }): SortState => ({ column, direction }),
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

        sessionTracesErrors: [
            new Set<string>() as Set<string>,
            {
                loadSessionTracesFailure: (state, { sessionId }) => new Set(state).add(sessionId),
                loadSessionTracesSuccess: (state, { sessionId }) => {
                    const newSet = new Set(state)
                    newSet.delete(sessionId)
                    return newSet
                },
                setDates: () => new Set<string>(),
                setPropertyFilters: () => new Set<string>(),
                setShouldFilterTestAccounts: () => new Set<string>(),
            },
        ],

        fullTracesErrors: [
            new Set<string>() as Set<string>,
            {
                loadFullTraceFailure: (state, { traceId }) => new Set(state).add(traceId),
                loadFullTraceSuccess: (state, { traceId }) => {
                    const newSet = new Set(state)
                    newSet.delete(traceId)
                    return newSet
                },
                setDates: () => new Set<string>(),
                setPropertyFilters: () => new Set<string>(),
                setShouldFilterTestAccounts: () => new Set<string>(),
            },
        ],
    }),

    listeners(({ actions, values }) => ({
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

            const tracesQuerySource: TracesQuery = {
                kind: NodeKind.TracesQuery,
                dateRange: {
                    date_from: dateFrom,
                    date_to: dateTo,
                },
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$ai_session_id',
                        operator: PropertyOperator.Exact,
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
    })),

    selectors({
        sessionsQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.sessionsSort,
                s.groupsTaxonomicTypes,
            ],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters,
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
    }),
])
