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

// Heavy AI props are extracted into dedicated `ai_events` columns; the
// renderer expects them merged back into `properties` (same shape that
// `merge_heavy_properties` produces on the backend for TraceQuery).
const HEAVY_COLUMN_KEYS: readonly string[] = [
    '$ai_input',
    '$ai_output',
    '$ai_output_choices',
    '$ai_input_state',
    '$ai_output_state',
    '$ai_tools',
]

function parseEventRow(row: unknown[]): { traceId: string; event: LLMTraceEvent } {
    // ai_events rows carry 6 trailing heavy columns; the events fallback rows
    // have none. `heavy` is `[]` in the latter case, so the merge loop below
    // is a no-op without needing an explicit branch.
    const [traceId, id, event, createdAt, properties, ...heavy] = row as [
        string,
        string,
        string,
        string,
        string,
        ...(string | null)[],
    ]
    // ClickHouse hands `properties` back as a JSON-encoded String column.
    // If parsing fails (corruption, encoding bug, schema drift) render the
    // event with empty properties rather than failing the whole bulk load.
    let parsedProperties: Record<string, any> = {}
    try {
        const parsed = JSON.parse(properties)
        if (parsed && typeof parsed === 'object') {
            parsedProperties = parsed
        }
    } catch (parseError) {
        console.warn('Failed to parse event properties JSON', { id, parseError })
    }
    for (let i = 0; i < HEAVY_COLUMN_KEYS.length; i++) {
        const raw = heavy[i]
        if (raw == null || raw === '') {
            continue
        }
        const key = HEAVY_COLUMN_KEYS[i]
        try {
            parsedProperties[key] = JSON.parse(raw)
        } catch (parseError) {
            // Heavy columns are raw JSON snippets — leave the string in
            // place rather than dropping the field if parsing fails.
            parsedProperties[key] = raw
            console.warn('Failed to parse heavy AI column JSON', { id, key, parseError })
        }
    }
    return {
        traceId,
        event: {
            id,
            event,
            createdAt,
            properties: parsedProperties,
        },
    }
}

// Absorbs ingestion lag between an event firing and ClickHouse visibility (Mirrors `CAPTURE_RANGE_MINUTES = 10`)
const INGESTION_LAG_BUFFER_MS = 10 * 60 * 1000

// `trace.createdAt` is the trace's earliest event timestamp. Later events within the
// same trace (final $ai_generation, summary $ai_metric, completion $ai_trace) can land
// after that
const LATE_EVENTS_WINDOW_MS = 24 * 60 * 60 * 1000

function buildEventsFallbackQuery(sessionId: string, traces: LLMTrace[]): HogQLQuery | null {
    const traceTimestamps = traces
        .map((trace) => new Date(trace.createdAt).getTime())
        .filter((ts) => Number.isFinite(ts))
    if (traceTimestamps.length === 0) {
        return null
    }
    // Capping by timestamp for performance
    const minTs = new Date(Math.min(...traceTimestamps) - INGESTION_LAG_BUFFER_MS).toISOString()
    const maxTs = new Date(Math.max(...traceTimestamps) + LATE_EVENTS_WINDOW_MS).toISOString()
    const traceIds = traces.map((trace) => trace.id).filter((id) => typeof id === 'string' && id !== '')
    return {
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
              AND properties.$ai_trace_id IN {traceIds}
              AND timestamp >= toDateTime({minTs})
              AND timestamp <= toDateTime({maxTs})
            ORDER BY trace_id, timestamp
            LIMIT 20000
        `,
        values: { sessionId, traceIds, minTs, maxTs },
    }
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
            // Primary path: ai_events. Sort key (team_id, trace_id, timestamp) + bloom_filter
            // on session_id; the bulk-stripped heavy AI props live in dedicated columns here
            // (events.properties no longer carries them on rolled-out teams).
            // Explicit LIMIT to not truncate using a default limit.
            // Excluding session-scoped events that have no ai_trace_id —
            // mostly ai_metric and ai_embedding events.
            const aiEventsQuery: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: `
                    SELECT
                        toString(trace_id) AS trace_id,
                        toString(uuid) AS id,
                        event,
                        toString(timestamp) AS created_at,
                        properties,
                        input,
                        output,
                        output_choices,
                        input_state,
                        output_state,
                        tools
                    FROM posthog.ai_events
                    WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_metric', '$ai_feedback', '$ai_embedding')
                      AND session_id = {sessionId}
                      AND trace_id != ''
                    ORDER BY trace_id, timestamp
                    LIMIT 20000
                `,
                values: { sessionId },
            }
            try {
                const aiEventsResponse = await api.query(aiEventsQuery)
                const grouped: Record<string, LLMTraceEvent[]> = {}
                for (const row of aiEventsResponse.results ?? []) {
                    const { traceId, event } = parseEventRow(row as unknown[])
                    if (!grouped[traceId]) {
                        grouped[traceId] = []
                    }
                    grouped[traceId].push(event)
                }

                // ai_events has a 30-day TTL so we might not have full coverage.
                // Two cases:
                // 1. Entirely older session
                // 2. Long-lived session with some recent and some old traces
                const missingTraces = values.traces.filter((trace) => !(trace.id in grouped))
                if (missingTraces.length > 0) {
                    const fallbackQuery = buildEventsFallbackQuery(sessionId, missingTraces)
                    if (fallbackQuery) {
                        const fallbackResponse = await api.query(fallbackQuery)
                        for (const row of fallbackResponse.results ?? []) {
                            const { traceId, event } = parseEventRow(row as unknown[])
                            if (!grouped[traceId]) {
                                grouped[traceId] = []
                            }
                            grouped[traceId].push(event)
                        }
                    }
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
                // `loadAllSessionEvents` normally pre-populates `fullTraces`,
                // and bulk-loaded events work identically as input to
                // `restoreTree` (which walks parent links via
                // `properties.$ai_parent_id`). The per-trace `TraceQuery`
                // below only runs as a fallback when the bulk load failed
                // or didn't include this trace.
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
