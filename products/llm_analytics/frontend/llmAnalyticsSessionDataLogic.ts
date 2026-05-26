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
    HogQLQuery,
    LLMTrace,
    LLMTraceEvent,
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
        loadAllSessionEvents: true,
        loadAllSessionEventsSuccess: (tracesWithEvents: LLMTrace[]) => ({ tracesWithEvents }),
        loadAllSessionEventsFailure: (error: string) => ({ error }),
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
                loadAllSessionEventsSuccess: (state, { tracesWithEvents }) => {
                    const next = { ...state }
                    for (const trace of tracesWithEvents) {
                        next[trace.id] = trace
                    }
                    return next
                },
            },
        ],
        bulkLoading: [
            false,
            {
                loadAllSessionEvents: () => true,
                loadAllSessionEventsSuccess: () => false,
                loadAllSessionEventsFailure: () => false,
            },
        ],
        bulkLoadError: [
            null as string | null,
            {
                loadAllSessionEvents: () => null,
                loadAllSessionEventsSuccess: () => null,
                loadAllSessionEventsFailure: (_, { error }) => error,
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

    listeners(({ actions, values, props }) => ({
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
        loadAllSessionEvents: async () => {
            const sessionId = props.sessionId
            if (!sessionId || values.traces.length === 0) {
                actions.loadAllSessionEventsSuccess([])
                return
            }
            // Explicit LIMIT to not truncate using a default limit.
            // Excluding session-scoped events that have no ai_trace_id —
            // mostly ai_metric and ai_embedding events.
            const eventsQuery: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: `
                    SELECT
                        toString(properties.$ai_trace_id) AS trace_id,
                        toString(uuid) AS id,
                        event,
                        toString(timestamp) AS created_at,
                        properties
                    FROM events
                    WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_metric', '$ai_feedback', '$ai_embedding')
                      AND properties.$ai_session_id = {sessionId}
                      AND properties.$ai_trace_id != ''
                    ORDER BY trace_id, timestamp
                    LIMIT 20000
                `,
                values: { sessionId },
            }
            try {
                const response = await api.query(eventsQuery)
                const grouped: Record<string, LLMTraceEvent[]> = {}
                for (const row of response.results ?? []) {
                    const [traceId, id, event, createdAt, properties] = row as [string, string, string, string, string]
                    // ClickHouse hands `properties` back as a JSON-encoded
                    // String column. If parsing fails (corruption, encoding
                    // bug, schema drift) render the event with empty
                    // properties rather than failing the whole bulk load.
                    let parsedProperties: Record<string, any> = {}
                    try {
                        const parsed = JSON.parse(properties)
                        if (parsed && typeof parsed === 'object') {
                            parsedProperties = parsed
                        }
                    } catch (parseError) {
                        console.warn('Failed to parse event properties JSON', { id, parseError })
                    }
                    if (!grouped[traceId]) {
                        grouped[traceId] = []
                    }
                    grouped[traceId].push({
                        id,
                        event,
                        createdAt,
                        properties: parsedProperties,
                    })
                }
                // Fallback to `[]` covers the rare case where a trace's
                // events were truncated by the LIMIT.
                const tracesWithEvents = values.traces.map((trace) => ({
                    ...trace,
                    events: grouped[trace.id] ?? [],
                }))
                actions.loadAllSessionEventsSuccess(tracesWithEvents)
            } catch (error) {
                const message = error instanceof Error ? error.message : 'Unknown error'
                console.error('Error loading bulk session events:', error)
                actions.loadAllSessionEventsFailure(message)
            }
        },
        summarizeAllTraces: async () => {
            if (!values.dataProcessingAccepted) {
                return
            }
            const hasSummaries = Object.keys(values.traceSummaries).length > 0
            for (const trace of values.traces) {
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
                // First fetch the full trace with all events. The bulk session
                // events query in `loadAllSessionEvents` covers the conversation
                // view, but `restoreTree` needs the full nested event tree —
                // which `TraceQuery` provides per-trace. Falls back to fetching
                // if the trace isn't already in `fullTraces`.
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
    })),

    subscriptions(({ actions, values }) => ({
        traces: (traces: LLMTrace[]) => {
            if (traces.length === 0) {
                return
            }
            // Cache lookup for existing trace summaries
            if (Object.keys(values.traceSummaries).length === 0) {
                actions.loadCachedSummaries(traces.map((t) => t.id))
            }
            // Fire bulk fetch on initial mount and on pagination
            const hasUnloadedTrace = traces.some((t) => !values.fullTraces[t.id])
            if (!values.bulkLoading && hasUnloadedTrace) {
                actions.loadAllSessionEvents()
            }
        },
    })),
])
