import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import api, { getCookie } from 'lib/api'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

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
        ],
    })),

    actions({
        toggleTraceExpanded: (traceId: string) => ({ traceId }),
        toggleGenerationExpanded: (generationId: string) => ({ generationId }),
        loadFullTrace: (traceId: string) => ({ traceId }),
        loadFullTraceSuccess: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        loadFullTraceFailure: (traceId: string) => ({ traceId }),
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
        isSummarizingSession: [
            false,
            {
                summarizeAllTraces: () => true,
                clearTraceSummaries: () => false,
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
        hasSummaries: [
            (s) => [s.traceSummaries],
            (traceSummaries: Record<string, TraceSummary>): boolean => Object.keys(traceSummaries).length > 0,
        ],
        summariesLoading: [
            (s) => [s.traceSummaries],
            (traceSummaries: Record<string, TraceSummary>): boolean =>
                Object.values(traceSummaries).some((s) => s.loading),
        ],
    }),

    listeners(({ actions, values }) => ({
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
            const teamId = (window as any).POSTHOG_APP_CONTEXT?.current_team?.id
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

                const payload = {
                    summarize_type: 'trace',
                    mode: 'minimal',
                    force_refresh: forceRefresh,
                    data: {
                        trace: fullTrace,
                        hierarchy,
                    },
                }

                const url = `/api/environments/${teamId}/llm_analytics/summarization/`
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('posthog_csrftoken') || '',
                    },
                    body: JSON.stringify(payload),
                    credentials: 'include',
                })

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}))
                    throw new Error(errorData.detail || errorData.error || 'Failed to generate summary')
                }

                const data = await response.json()
                actions.summarizeTraceSuccess(traceId, data.summary?.title || 'Untitled trace')
            } catch (error) {
                actions.summarizeTraceFailure(traceId, error instanceof Error ? error.message : 'Unknown error')
            }
        },
    })),
])
