import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    mcpAnalyticsSessionsGenerateIntent,
    mcpAnalyticsSessionsList,
    mcpAnalyticsSessionsToolCalls,
} from '../generated/api'
import type { MCPSessionApi, MCPSessionIntentApi, MCPToolCallApi } from '../generated/api.schemas'
import type { mcpSessionsLogicType } from './mcpSessionsLogicType'

export interface MCPSessionsFilters {
    search: string
}

const DEFAULT_FILTERS: MCPSessionsFilters = {
    search: '',
}

export interface MCPSessionsDateFilter {
    dateFrom: string | null
    dateTo: string | null
}

// Matches the dashboard default (mcpDashboardOverviewLogic) so both tabs show the
// same window out of the box and the shared date_from/date_to URL params line up.
const DEFAULT_DATE_FILTER: MCPSessionsDateFilter = { dateFrom: '-7d', dateTo: null }

const SEARCH_DEBOUNCE_MS = 300

// How many sessions to fetch per request. Each "Load more" appends the next page
export const SESSIONS_PAGE_SIZE = 50

// How many of a session's tool calls to fetch per request. Each "Load more" appends the
// next page; the button appears whenever a session has more calls than one page.
export const TOOL_CALLS_PAGE_SIZE = 100

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

export type MCPSessionOrderBy = `${'' | '-'}${MCPSessionSortColumn}`

export function orderByParam(sorting: MCPSessionSorting | null): MCPSessionOrderBy | undefined {
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
        loadMoreToolCalls: true,
        setFilters: (filters: Partial<MCPSessionsFilters>) => ({ filters }),
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSorting: (sorting: MCPSessionSorting | null) => ({ sorting }),
        setHasNext: (hasNext: boolean) => ({ hasNext }),
        setToolCallsHasNext: (hasNext: boolean) => ({ hasNext }),
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
                        date_from: values.dateFilter.dateFrom || undefined,
                        date_to: values.dateFilter.dateTo || undefined,
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
                    const dateFrom = values.dateFilter.dateFrom
                    const dateTo = values.dateFilter.dateTo
                    const response = await mcpAnalyticsSessionsList(String(values.currentProjectId), {
                        search: search || undefined,
                        order_by: orderBy,
                        date_from: dateFrom || undefined,
                        date_to: dateTo || undefined,
                        limit: SESSIONS_PAGE_SIZE,
                        offset: baseSessions.length,
                    })
                    if (
                        search !== values.filters.search ||
                        orderBy !== orderByParam(values.sorting) ||
                        dateFrom !== values.dateFilter.dateFrom ||
                        dateTo !== values.dateFilter.dateTo
                    ) {
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
                // First page for a session. Replaces the list.
                loadToolCalls: async (sessionId: string, breakpoint) => {
                    if (!values.currentProjectId || !sessionId) {
                        return []
                    }
                    // session_id comes from untrusted event properties — encode it so path/query
                    // delimiters can't redirect this request to another same-origin endpoint.
                    // Pass the session's start as the scan bound so sessions older than the
                    // backend's default lookback still return their tool calls.
                    const session = values.sessions.find((s) => s.session_id === sessionId)
                    const response = await mcpAnalyticsSessionsToolCalls(
                        String(values.currentProjectId),
                        encodeURIComponent(sessionId),
                        { date_from: session?.session_start || undefined, limit: TOOL_CALLS_PAGE_SIZE, offset: 0 }
                    )
                    breakpoint()
                    actions.setToolCallsHasNext(response.has_next ?? false)
                    return [...(response.results ?? [])]
                },
                // Load more: append the next page at offset = current length.
                loadMoreToolCalls: async () => {
                    const sessionId = values.selectedSessionId
                    if (!values.currentProjectId || !sessionId) {
                        return values.toolCalls
                    }
                    // Snapshot the list before the await. If the user selects another session while
                    // this page is in flight, merging against the new session's calls would corrupt
                    // the list — so offset from the snapshot and drop the page if the selection changed.
                    const baseCalls = values.toolCalls
                    const session = values.sessions.find((s) => s.session_id === sessionId)
                    const response = await mcpAnalyticsSessionsToolCalls(
                        String(values.currentProjectId),
                        encodeURIComponent(sessionId),
                        {
                            date_from: session?.session_start || undefined,
                            limit: TOOL_CALLS_PAGE_SIZE,
                            offset: baseCalls.length,
                        }
                    )
                    if (sessionId !== values.selectedSessionId) {
                        return values.toolCalls
                    }
                    actions.setToolCallsHasNext(response.has_next ?? false)
                    return [...baseCalls, ...(response.results ?? [])]
                },
            },
        ],
        generatedIntent: [
            null as MCPSessionIntentApi | null,
            {
                generateIntent: async (sessionId: string) => {
                    if (!values.currentProjectId || !sessionId) {
                        return null
                    }
                    // session_id comes from untrusted event properties — encode it so path/query
                    // delimiters can't redirect this POST to another same-origin endpoint. Bound the
                    // intent scan by the session's start so older sessions resolve, mirroring loadToolCalls.
                    const session = values.sessions.find((s) => s.session_id === sessionId)
                    return await mcpAnalyticsSessionsGenerateIntent(
                        String(values.currentProjectId),
                        encodeURIComponent(sessionId),
                        { date_from: session?.session_start || undefined }
                    )
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
        dateFilter: [
            DEFAULT_DATE_FILTER,
            {
                setDateFilter: (_, { dateFrom, dateTo }): MCPSessionsDateFilter => ({ dateFrom, dateTo }),
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
        toolCallsHasNext: [
            false,
            {
                setToolCallsHasNext: (_, { hasNext }) => hasNext,
                // Reset when a new session's first page starts loading; setToolCallsHasNext
                // restores it once that page resolves.
                loadToolCalls: () => false,
            },
        ],
        // Distinguishes a "Load more" append from the initial per-session load, so the panel
        // keeps its existing calls (and only the button spins) while the next page fetches.
        toolCallsLoadingMore: [
            false,
            {
                loadMoreToolCalls: () => true,
                loadMoreToolCallsSuccess: () => false,
                loadMoreToolCallsFailure: () => false,
                loadToolCalls: () => false,
            },
        ],
        intentOverrides: [
            {} as Record<string, string>,
            {
                generateIntentSuccess: (state, { generatedIntent }) =>
                    generatedIntent?.intent
                        ? { ...state, [generatedIntent.session_id]: generatedIntent.intent }
                        : state,
            },
        ],
        generatingSessionId: [
            null as string | null,
            {
                generateIntent: (_, sessionId) => sessionId,
                generateIntentSuccess: () => null,
                generateIntentFailure: () => null,
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
        selectedSessionIntent: [
            (s) => [s.selectedSession, s.intentOverrides, s.selectedSessionId],
            (selectedSession, intentOverrides, selectedSessionId): string => {
                if (selectedSessionId && intentOverrides[selectedSessionId]) {
                    return intentOverrides[selectedSessionId]
                }
                return selectedSession?.intent ?? ''
            },
        ],
        // True only while a generation for the *currently selected* session is running, so a
        // generation kicked off for another session never shows a spinner on this one.
        isSelectedSessionGenerating: [
            (s) => [s.generatedIntentLoading, s.generatingSessionId, s.selectedSessionId],
            (generatedIntentLoading, generatingSessionId, selectedSessionId): boolean =>
                generatedIntentLoading && generatingSessionId === selectedSessionId,
        ],
    }),
    listeners(({ actions, values }) => ({
        // A new filter or sort changes the result set — reload from the first page.
        setFilters: () => {
            actions.loadSessions()
        },
        setDateFilter: () => {
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
        // The button just resets to its idle state on failure; surface a toast so the user
        // knows the request failed (e.g. a 503 when intent generation is unavailable).
        generateIntentFailure: () => {
            lemonToast.error('Could not generate the session intent. Please try again.')
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
    // date_from / date_to are shared with the dashboard via the URL: the scene's tab links
    // carry searchParams across tabs, so a range picked on either tab follows to the other.
    actionToUrl(({ values }) => {
        const syncUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            if (values.dateFilter.dateFrom) {
                searchParams.date_from = values.dateFilter.dateFrom
            } else {
                delete searchParams.date_from
            }
            if (values.dateFilter.dateTo) {
                searchParams.date_to = values.dateFilter.dateTo
            } else {
                delete searchParams.date_to
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            setDateFilter: syncUrl,
        }
    }),
    urlToAction(({ actions, values, cache }) => ({
        [urls.mcpAnalyticsSessions()]: (_, searchParams) => {
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : DEFAULT_DATE_FILTER.dateFrom
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            const dateChanged = dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo
            // setDateFilter reloads via its listener; only load directly when nothing changed.
            if (dateChanged) {
                actions.setDateFilter(dateFrom, dateTo)
            } else if (!cache.hasLoaded) {
                actions.loadSessions()
            }
            cache.hasLoaded = true
        },
    })),
    afterMount(({ actions, cache }) => {
        // urlToAction owns the initial load when the sessions URL carries date params; this is the
        // fallback for a param-less mount (and off-route mounts in tests, where urlToAction never
        // fires). The cache.hasLoaded guard keeps a deep-linked load from firing twice.
        const { searchParams } = router.values
        const hasUrlDates = typeof searchParams.date_from === 'string' || typeof searchParams.date_to === 'string'
        if (!hasUrlDates && !cache.hasLoaded) {
            cache.hasLoaded = true
            actions.loadSessions()
        }
    }),
])
