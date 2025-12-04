import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import {
    AnyResponseType,
    DataTableNode,
    LLMTrace,
    NodeKind,
    TraceQuery,
    TracesQueryResponse,
} from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { llmAnalyticsSessionDataLogicType } from './llmAnalyticsSessionDataLogicType'
import { llmAnalyticsSessionLogic } from './llmAnalyticsSessionLogic'
import { restoreTree } from './llmAnalyticsTraceDataLogic'

export interface TraceSummary {
    title: string
    traceId: string
    loading: boolean
    error: string | null
}

export interface SessionDataLogicProps {
    sessionId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

function getDataNodeLogicProps({ sessionId, query, cachedResults }: SessionDataLogicProps): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Session.${sessionId}`,
        dataNodeCollectionId: sessionId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: sessionId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export const llmAnalyticsSessionDataLogic = kea<llmAnalyticsSessionDataLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsSessionDataLogic']),
    props({} as SessionDataLogicProps),
    connect((props: SessionDataLogicProps) => ({
        values: [
            llmAnalyticsSessionLogic,
            ['sessionId'],
            dataNodeLogic(getDataNodeLogicProps(props)),
            ['response', 'responseLoading', 'responseError'],
            maxGlobalLogic,
            ['dataProcessingAccepted'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),

    actions({
        toggleTraceExpanded: (traceId: string) => ({ traceId }),
        toggleGenerationExpanded: (generationId: string) => ({ generationId }),
        loadFullTrace: (traceId: string) => ({ traceId }),
        loadFullTraceSuccess: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        loadFullTraceFailure: (traceId: string) => ({ traceId }),
        loadCachedSummaries: (traceIds: string[]) => ({ traceIds }),
        loadCachedSummariesSuccess: (summaries: Array<{ trace_id: string; title: string }>) => ({ summaries }),
        summarizeAllTraces: true,
        summarizeTrace: (traceId: string, forceRefresh: boolean = false) => ({ traceId, forceRefresh }),
        summarizeTraceSuccess: (traceId: string, title: string) => ({ traceId, title }),
        summarizeTraceFailure: (traceId: string, error: string) => ({ traceId, error }),
        clearTraceSummaries: true,
    }),

    reducers({
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
            },
        ],
        expandedGenerationIds: [
            new Set<string>() as Set<string>,
            {
                toggleGenerationExpanded: (state, { generationId }) => {
                    const newSet = new Set(state)
                    if (newSet.has(generationId)) {
                        newSet.delete(generationId)
                    } else {
                        newSet.add(generationId)
                    }
                    return newSet
                },
            },
        ],
        fullTraces: [
            {} as Record<string, LLMTrace>,
            {
                loadFullTraceSuccess: (state, { traceId, trace }) => ({
                    ...state,
                    [traceId]: trace,
                }),
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
        traceSummaries: [
            {} as Record<string, TraceSummary>,
            {
                loadCachedSummariesSuccess: (state, { summaries }) => {
                    const newState = { ...state }
                    for (const summary of summaries) {
                        newState[summary.trace_id] = {
                            traceId: summary.trace_id,
                            title: summary.title,
                            loading: false,
                            error: null,
                        }
                    }
                    return newState
                },
                summarizeTrace: (state, { traceId }) => ({
                    ...state,
                    [traceId]: { traceId, title: '', loading: true, error: null },
                }),
                summarizeTraceSuccess: (state, { traceId, title }) => ({
                    ...state,
                    [traceId]: { traceId, title, loading: false, error: null },
                }),
                summarizeTraceFailure: (state, { traceId, error }) => ({
                    ...state,
                    [traceId]: { ...state[traceId], loading: false, error },
                }),
                clearTraceSummaries: () => ({}),
            },
        ],
    }),

    selectors({
        traces: [
            (s) => [s.response],
            (response: AnyResponseType | null): LLMTrace[] => {
                const tracesResponse = response as TracesQueryResponse | null
                return tracesResponse?.results || []
            },
        ],
        summariesLoading: [
            (s) => [s.traceSummaries],
            (traceSummaries: Record<string, TraceSummary>): boolean =>
                Object.values(traceSummaries).some((s) => s.loading),
        ],
    }),

    listeners(({ actions, values }) => ({
        loadCachedSummaries: async ({ traceIds }) => {
            if (traceIds.length === 0) {
                return
            }

            if (!values.dataProcessingAccepted) {
                return
            }

            const teamId = values.currentTeamId
            if (!teamId) {
                return
            }

            try {
                const data = await api.create(`api/environments/${teamId}/llm_analytics/summarization/batch_check/`, {
                    trace_ids: traceIds,
                    mode: 'minimal',
                })

                if (data.summaries && data.summaries.length > 0) {
                    actions.loadCachedSummariesSuccess(data.summaries)
                }
            } catch {
                // Silently fail - this is just a cache optimization
            }
        },
        toggleTraceExpanded: async ({ traceId }) => {
            if (
                values.expandedTraceIds.has(traceId) &&
                !values.fullTraces[traceId] &&
                !values.loadingFullTraces.has(traceId)
            ) {
                actions.loadFullTrace(traceId)

                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                }

                try {
                    const response = await api.query(traceQuery)
                    if (response.results && response.results[0]) {
                        actions.loadFullTraceSuccess(traceId, response.results[0])
                    } else {
                        actions.loadFullTraceFailure(traceId)
                    }
                } catch (error) {
                    console.error('Error loading full trace:', error)
                    actions.loadFullTraceFailure(traceId)
                }
            }
        },
        summarizeAllTraces: async () => {
            if (!values.dataProcessingAccepted) {
                return
            }

            const hasSummaries = Object.keys(values.traceSummaries).length > 0
            const traces = values.traces
            for (const trace of traces) {
                actions.summarizeTrace(trace.id, hasSummaries)
            }
        },
        summarizeTrace: async ({ traceId, forceRefresh }) => {
            const teamId = values.currentTeamId
            if (!teamId) {
                actions.summarizeTraceFailure(traceId, 'Team ID not available')
                return
            }

            try {
                // First fetch the full trace with all events (session query only has direct children)
                let fullTrace: LLMTrace | undefined = values.fullTraces[traceId]
                if (!fullTrace) {
                    const traceQuery: TraceQuery = {
                        kind: NodeKind.TraceQuery,
                        traceId,
                    }
                    const traceResponse = await api.query(traceQuery)
                    if (traceResponse.results && traceResponse.results[0]) {
                        fullTrace = traceResponse.results[0]
                    } else {
                        throw new Error('Failed to load full trace')
                    }
                }

                // Build the hierarchy tree from full trace events
                const hierarchy = restoreTree(fullTrace.events || [], traceId)

                const data = await api.create(`api/environments/${teamId}/llm_analytics/summarization/`, {
                    summarize_type: 'trace',
                    mode: 'minimal',
                    force_refresh: forceRefresh,
                    data: {
                        trace: fullTrace,
                        hierarchy,
                    },
                })

                actions.summarizeTraceSuccess(traceId, data.summary?.title || 'Untitled trace')
            } catch (error) {
                actions.summarizeTraceFailure(traceId, error instanceof Error ? error.message : 'Unknown error')
            }
        },
    })),

    subscriptions(({ actions, values }) => ({
        traces: (traces: LLMTrace[]) => {
            // Load cached summaries when traces are loaded
            if (traces.length > 0 && Object.keys(values.traceSummaries).length === 0) {
                const traceIds = traces.map((t) => t.id)
                actions.loadCachedSummaries(traceIds)
            }
        },
    })),
])
