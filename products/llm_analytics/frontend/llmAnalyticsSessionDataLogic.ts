import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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

import { SessionTurn, extractSessionTurns } from './extractSessionTurns'
import { llmAnalyticsSummarizationBatchCheckCreate } from './generated/api'
import type { llmAnalyticsSessionDataLogicType } from './llmAnalyticsSessionDataLogicType'
import { llmAnalyticsSessionLogic } from './llmAnalyticsSessionLogic'
import { restoreTree } from './llmAnalyticsTraceDataLogic'

export interface TraceSummary {
    title: string
    traceId: string
    loading: boolean
    error: string | null
}

// Eager-load the first N traces on mount; later turns render a "Show conversation"
// button. Picking first N and not first and last N, because cross-trace dedup walks
// chronologically and accumulates `seenSignatures`; any gap in loaded turns would
// let the later turns' running history show as "new" content.
// Most sessions have less than 10 turns, a proper fix later is a bulk query.
const AUTO_LOAD_LIMIT = 10

export interface SessionDataLogicProps {
    sessionId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
    tabId?: string
}

function getDataNodeLogicProps({ sessionId, query, cachedResults, tabId }: SessionDataLogicProps): DataNodeLogicProps {
    const tabScope = tabId ?? 'default'
    const scopedSessionId = `${sessionId}:${tabScope}`
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Session.${scopedSessionId}`,
        dataNodeCollectionId: scopedSessionId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: scopedSessionId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export const llmAnalyticsSessionDataLogic = kea<llmAnalyticsSessionDataLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsSessionDataLogic']),
    props({} as SessionDataLogicProps),
    key((props) => `${props.sessionId}:${props.tabId ?? 'default'}`),
    connect((props: SessionDataLogicProps) => ({
        values: [
            llmAnalyticsSessionLogic({ tabId: props.tabId }),
            ['sessionId'],
            dataNodeLogic(getDataNodeLogicProps(props)),
            ['response', 'responseLoading', 'responseError', 'canLoadNextData', 'hasMoreData', 'nextDataLoading'],
            maxGlobalLogic,
            ['dataProcessingAccepted'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [dataNodeLogic(getDataNodeLogicProps(props)), ['loadNextData']],
    })),

    actions({
        // Steps panel = the per-turn `LLMAnalyticsTraceEvents` tree shown via the
        // "Show steps" link. Distinct from "trace loaded" because the conversation
        // bubbles render as soon as the full trace is fetched, regardless of steps state.
        toggleSteps: (traceId: string) => ({ traceId }),
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
        stepsExpandedTraceIds: [
            new Set<string>() as Set<string>,
            {
                toggleSteps: (state, { traceId }) => {
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
                // Reverse to chronological order (oldest first) for session view
                return [...(tracesResponse?.results || [])].reverse()
            },
        ],
        sessionTurns: [
            (s) => [s.traces, s.fullTraces],
            (traces: LLMTrace[], fullTraces: Record<string, LLMTrace>): SessionTurn[] =>
                extractSessionTurns(traces, fullTraces),
        ],
        summariesLoading: [
            (s) => [s.traceSummaries],
            (traceSummaries: Record<string, TraceSummary>): boolean =>
                Object.values(traceSummaries).some((s) => s.loading),
        ],
    }),

    listeners(({ actions, values }) => {
        // Closure-scoped in-flight lock for `loadFullTrace`. Mirrors the pattern used
        // by sibling lazy loaders in this product (llmPersonsLazyLoaderLogic,
        // llmSentimentLazyLoaderLogic, traceReviewsLazyLoaderLogic, etc.). We can't
        // rely on `values.loadingFullTraces` for this guard because kea reducers run
        // synchronously *before* listeners — so the reducer has already added this
        // traceId by the time the listener checks. The closure-scoped Set lets the
        // listener distinguish "this dispatch's reducer just added the id" from
        // "a prior dispatch is still mid-flight".
        const inFlightTraceFetches = new Set<string>()

        return {
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
                    const data = await llmAnalyticsSummarizationBatchCheckCreate(String(teamId), {
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
            loadFullTrace: async ({ traceId }) => {
                if (values.fullTraces[traceId] || inFlightTraceFetches.has(traceId)) {
                    return
                }
                inFlightTraceFetches.add(traceId)
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
                } finally {
                    inFlightTraceFetches.delete(traceId)
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

                    // nosemgrep: prefer-codegen-api
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
        }
    }),

    subscriptions(({ actions, values }) => ({
        traces: (traces: LLMTrace[]) => {
            if (traces.length === 0) {
                return
            }
            // Cache lookup for existing trace summaries
            if (Object.keys(values.traceSummaries).length === 0) {
                actions.loadCachedSummaries(traces.map((t) => t.id))
            }
            for (const trace of traces.slice(0, AUTO_LOAD_LIMIT)) {
                if (!values.fullTraces[trace.id] && !values.loadingFullTraces.has(trace.id)) {
                    actions.loadFullTrace(trace.id)
                }
            }
        },
    })),
])
