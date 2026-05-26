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

const DEFAULT_SORTING: MCPSessionSorting = { column: 'session_end', order: -1 }

export const mcpSessionsLogic = kea<mcpSessionsLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'sessions', 'mcpSessionsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        // Declared explicitly so kea-typegen emits a no-arg signature for the loader
        // action below — without this, the `(_, breakpoint)` loader signature forces
        // every call site to pass a placeholder argument.
        loadSessions: true,
        setFilters: (filters: Partial<MCPSessionsFilters>) => ({ filters }),
        setSorting: (sorting: MCPSessionSorting | null) => ({ sorting }),
        selectSession: (sessionId: string | null) => ({ sessionId }),
    }),
    loaders(({ values }) => ({
        sessions: [
            [] as MCPSessionApi[],
            {
                loadSessions: async (_, breakpoint) => {
                    // Debounce keystroke-driven loads. afterMount fires loadSessions with no
                    // payload, in which case we still want the initial fetch to be fast — so
                    // only honour the debounce when there is a search term.
                    if (values.filters.search) {
                        await breakpoint(SEARCH_DEBOUNCE_MS)
                    }
                    if (!values.currentProjectId) {
                        return []
                    }
                    const sorting = values.sorting
                    const orderBy = sorting ? `${sorting.order === -1 ? '-' : ''}${sorting.column}` : undefined
                    const response = await mcpAnalyticsSessionsList(String(values.currentProjectId), {
                        search: values.filters.search || undefined,
                        order_by: orderBy,
                    })
                    return [...(response.results ?? [])]
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
        loadSessionsSuccess: ({ sessions }) => {
            // Auto-select the first session whenever results come back. If the user
            // had a session pinned that is no longer in the filtered set, clear it.
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
