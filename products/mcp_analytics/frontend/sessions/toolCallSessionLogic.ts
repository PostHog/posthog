import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { mcpAnalyticsSessionsGenerateIntent, mcpAnalyticsSessionsList } from '../generated/api'
import type { MCPSessionApi, MCPToolCallApi } from '../generated/api.schemas'
import { type MCPSharedQueryFilters, mcpAnalyticsFiltersLogic, sharedFilterParams } from '../mcpAnalyticsFiltersLogic'
import { fetchToolCallsPage, scanBoundsOf } from './mcpSessionsLogic'
import type { MCPSessionToolCallsState } from './MCPSessionView'

export interface ToolCallSessionLogicProps {
    sessionId: string
    timestamp: string
}

interface LoadedSession {
    session: MCPSessionApi | null
    filters: MCPSharedQueryFilters
    calls: MCPToolCallApi[]
    hasNext: boolean
}

// A session spans minutes, so a day either side of the call finds all of it without scanning the whole date range.
const SESSION_LOOKUP_MARGIN_DAYS = 1

export const toolCallSessionLogic = kea([
    path((sessionId) => ['products', 'mcp_analytics', 'frontend', 'sessions', 'toolCallSessionLogic', sessionId]),
    props({} as ToolCallSessionLogicProps),
    key((props: ToolCallSessionLogicProps) => props.sessionId),
    connect(() => ({
        values: [teamLogic, ['currentProjectId'], mcpAnalyticsFiltersLogic, ['queryFilters as sharedQueryFilters']],
    })),
    actions({
        loadSession: true,
    }),
    loaders(({ props, values }) => ({
        loaded: [
            null as LoadedSession | null,
            {
                loadSession: async (_, breakpoint) => {
                    const projectId = String(values.currentProjectId)
                    const filters = values.sharedQueryFilters
                    const callTime = dayjs(props.timestamp)
                    // Session IDs are unique, so a search for one returns that session alone.
                    const response = await mcpAnalyticsSessionsList(projectId, {
                        search: props.sessionId,
                        limit: 1,
                        date_from: callTime.subtract(SESSION_LOOKUP_MARGIN_DAYS, 'day').toISOString(),
                        date_to: callTime.add(SESSION_LOOKUP_MARGIN_DAYS, 'day').toISOString(),
                        ...sharedFilterParams(filters),
                    })
                    breakpoint()
                    const session = response.results?.find((result) => result.session_id === props.sessionId) ?? null
                    if (!session) {
                        return { session, filters, calls: [], hasNext: false }
                    }
                    const scanBounds = scanBoundsOf(session, { dateFrom: null, dateTo: null })
                    const page = await fetchToolCallsPage(projectId, props.sessionId, scanBounds, 0, filters)
                    breakpoint()
                    return { session, filters, ...page }
                },
                loadMoreToolCalls: async () => {
                    const loaded = values.loaded
                    if (!loaded?.session) {
                        return loaded
                    }
                    const page = await fetchToolCallsPage(
                        String(values.currentProjectId),
                        props.sessionId,
                        scanBoundsOf(loaded.session, { dateFrom: null, dateTo: null }),
                        loaded.calls.length,
                        loaded.filters
                    )
                    return values.loaded === loaded
                        ? { ...loaded, calls: [...loaded.calls, ...page.calls], hasNext: page.hasNext }
                        : values.loaded
                },
            },
        ],
        generatedIntent: [
            null as string | null,
            {
                generateIntent: async () => {
                    const session = values.loaded?.session
                    if (!session) {
                        return null
                    }
                    const response = await mcpAnalyticsSessionsGenerateIntent(
                        String(values.currentProjectId),
                        encodeURIComponent(session.session_id),
                        { date_from: session.session_start }
                    )
                    return response.intent
                },
            },
        ],
    })),
    reducers({
        loadFailed: [
            false,
            {
                loadSession: () => false,
                loadSessionFailure: () => true,
            },
        ],
    }),
    selectors({
        session: [(s) => [s.loaded], (loaded: LoadedSession | null): MCPSessionApi | null => loaded?.session ?? null],
        toolCalls: [
            (s) => [s.loaded, s.loadedLoading, s.loadFailed],
            (loaded: LoadedSession | null, loading: boolean, failed: boolean): MCPSessionToolCallsState => ({
                calls: loaded?.calls ?? [],
                hasNext: !!loaded?.hasNext,
                loading: !loaded && loading,
                loadingMore: !!loaded && loading,
                error: failed,
            }),
        ],
        intent: [
            (s) => [s.session, s.generatedIntent],
            (session: MCPSessionApi | null, generatedIntent: string | null): string =>
                generatedIntent || session?.intent || '',
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSession()
    }),
])
