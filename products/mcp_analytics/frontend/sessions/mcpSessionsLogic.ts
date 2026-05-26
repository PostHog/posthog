import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { mcpAnalyticsSessionsList, mcpAnalyticsSessionsToolCalls } from '../generated/api'
import type { MCPSessionApi, MCPToolCallApi } from '../generated/api.schemas'
import type { mcpSessionsLogicType } from './mcpSessionsLogicType'

export interface MCPSessionsFilters {
    search: string
}

const DEFAULT_FILTERS: MCPSessionsFilters = {
    search: '',
}

const SEARCH_DEBOUNCE_MS = 300

// How many sessions to fetch per request. Each "Load more" appends the next page
export const SESSIONS_PAGE_SIZE = 50

// Must stay aligned with SESSION_SORT_FIELDS on the backend (logic.py).
export type MCPSessionSortColumn =
    | 'session_id'
    | 'session_start'
    | 'session_end'
    | 'duration_seconds'
    | 'tool_call_count'
    | 'mcp_client_name'
    | 'distinct_id'

export interface MCPSessionSorting {
    column: MCPSessionSortColumn
    order: 1 | -1
}

const DEFAULT_SORTING: MCPSessionSorting = { column: 'session_start', order: -1 }

function orderByParam(sorting: MCPSessionSorting | null): string | undefined {
    return sorting ? `${sorting.order === -1 ? '-' : ''}${sorting.column}` : undefined
}

export const mcpSessionsLogic = kea<mcpSessionsLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'sessions', 'mcpSessionsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        // Declared explicitly so kea-typegen emits a no-arg signature for the loader
        // actions below — without this, the `(_, breakpoint)` loader signature forces
        // every call site to pass a placeholder argument.
        loadSessions: true,
        loadMoreSessions: true,
        setFilters: (filters: Partial<MCPSessionsFilters>) => ({ filters }),
        setSorting: (sorting: MCPSessionSorting | null) => ({ sorting }),
        setHasNext: (hasNext: boolean) => ({ hasNext }),
        selectSession: (sessionId: string | null) => ({ sessionId }),
    }),
    loaders(({ values, actions }) => ({
        sessions: [
            [] as MCPSessionApi[],
            {
                // First page / reset (search or sort change). Replaces the list.
                loadSessions: async (_, breakpoint) => {
                    if (values.filters.search) {
                        await breakpoint(SEARCH_DEBOUNCE_MS)
                    }
                    if (!values.currentProjectId) {
                        return []
                    }
                    const response = await mcpAnalyticsSessionsList(String(values.currentProjectId), {
                        search: values.filters.search || undefined,
                        order_by: orderByParam(values.sorting),
                        limit: SESSIONS_PAGE_SIZE,
                        offset: 0,
                    })
                    actions.setHasNext(response.has_next ?? false)
                    return [...(response.results ?? [])]
                },
                // Load more: append the next page at offset = current length.
                loadMoreSessions: async () => {
                    if (!values.currentProjectId) {
                        return values.sessions
                    }
                    // Snapshot the list and the query (search + sort) before the await. If a
                    // concurrent loadSessions reset (sort/search change) lands while this page
                    // is in flight, merging against the post-await values.sessions would corrupt
                    // the list — so we both offset and merge from the snapshot, and drop this
                    // page entirely if the query changed underneath us.
                    const baseSessions = values.sessions
                    const search = values.filters.search
                    const orderBy = orderByParam(values.sorting)
                    const response = await mcpAnalyticsSessionsList(String(values.currentProjectId), {
                        search: search || undefined,
                        order_by: orderBy,
                        limit: SESSIONS_PAGE_SIZE,
                        offset: baseSessions.length,
                    })
                    if (search !== values.filters.search || orderBy !== orderByParam(values.sorting)) {
                        return values.sessions
                    }
                    actions.setHasNext(response.has_next ?? false)
                    return [...baseSessions, ...(response.results ?? [])]
                },
            },
        ],
        toolCalls: [
            [] as MCPToolCallApi[],
            {
                loadToolCalls: async (sessionId: string, breakpoint) => {
                    if (!values.currentProjectId || !sessionId) {
                        return []
                    }
                    const response = await mcpAnalyticsSessionsToolCalls(String(values.currentProjectId), sessionId)
                    breakpoint()
                    return [...(response.results ?? [])]
                },
            },
        ],
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        selectedSessionId: [
            null as string | null,
            {
                selectSession: (_, { sessionId }) => sessionId,
            },
        ],
        sorting: [
            DEFAULT_SORTING as MCPSessionSorting | null,
            {
                setSorting: (_, { sorting }) => sorting,
            },
        ],
        hasNext: [
            false,
            {
                setHasNext: (_, { hasNext }) => hasNext,
                // Hide "Load more" the moment a reset starts so it isn't shown (disabled,
                // spinning) during the reset; setHasNext restores it when the page resolves.
                loadSessions: () => false,
            },
        ],
    }),
    selectors({
        selectedSession: [
            (s) => [s.sessions, s.selectedSessionId],
            (sessions, selectedSessionId): MCPSessionApi | null => {
                if (!selectedSessionId) {
                    return null
                }
                return sessions.find((session) => session.session_id === selectedSessionId) ?? null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        // A new filter or sort changes the result set — reload from the first page.
        setFilters: () => {
            actions.loadSessions()
        },
        setSorting: () => {
            actions.loadSessions()
        },
        selectSession: ({ sessionId }) => {
            if (sessionId) {
                actions.loadToolCalls(sessionId)
            }
        },
        // Only fires on a reset load (not on loadMore), so appending more pages doesn't
        // steal the user's selection. Auto-selects the first row when the set changes.
        loadSessionsSuccess: ({ sessions }) => {
            if (sessions.length === 0) {
                if (values.selectedSessionId) {
                    actions.selectSession(null)
                }
                return
            }
            const stillVisible = values.selectedSessionId
                ? sessions.some((s) => s.session_id === values.selectedSessionId)
                : false
            if (!stillVisible) {
                actions.selectSession(sessions[0].session_id)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSessions()
    }),
])
