import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { mcpAnalyticsSessionsList, mcpAnalyticsSessionsToolCalls } from '../generated/api'
import type { McpAnalyticsSessionsToolCallsParams, MCPSessionApi, MCPToolCallApi } from '../generated/api.schemas'
import type { mcpSessionsLogicType } from './mcpSessionsLogicType'

export interface MCPSessionsFilters {
    search: string
}

const DEFAULT_FILTERS: MCPSessionsFilters = {
    search: '',
}

export const mcpSessionsLogic = kea<mcpSessionsLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'sessions', 'mcpSessionsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        setFilters: (filters: Partial<MCPSessionsFilters>) => ({ filters }),
        selectSession: (sessionId: string | null) => ({ sessionId }),
        setToolCallsTruncated: (truncated: boolean) => ({ truncated }),
    }),
    loaders(({ values, actions }) => ({
        allSessions: [
            [] as MCPSessionApi[],
            {
                loadSessions: async () => {
                    if (!values.currentProjectId) {
                        return []
                    }
                    const response = await mcpAnalyticsSessionsList(String(values.currentProjectId))
                    return [...(response.results ?? [])]
                },
            },
        ],
        toolCalls: [
            [] as MCPToolCallApi[],
            {
                loadToolCalls: async (sessionId: string) => {
                    if (!values.currentProjectId || !sessionId) {
                        actions.setToolCallsTruncated(false)
                        return []
                    }
                    // Pin the date window to the parent session's first_seen / last_seen
                    // (± 1 day for clock skew) so ClickHouse can prune partitions instead
                    // of scanning the full `events` table for a given $session_id.
                    const session = values.selectedSession
                    const params: McpAnalyticsSessionsToolCallsParams = {}
                    if (session) {
                        params.date_from = dayjs(session.first_seen).subtract(1, 'day').toISOString()
                        params.date_to = dayjs(session.last_seen).add(1, 'day').toISOString()
                    }
                    const response = await mcpAnalyticsSessionsToolCalls(
                        String(values.currentProjectId),
                        sessionId,
                        params
                    )
                    actions.setToolCallsTruncated(response.truncated ?? false)
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
        toolCallsTruncated: [
            false,
            {
                setToolCallsTruncated: (_, { truncated }) => truncated,
                selectSession: () => false,
            },
        ],
    }),
    selectors({
        sessions: [
            (s) => [s.allSessions, s.filters],
            (allSessions, filters): MCPSessionApi[] => {
                const term = filters.search.trim().toLowerCase()
                if (!term) {
                    return allSessions
                }
                return allSessions.filter((session) => {
                    if (session.session_id.toLowerCase().includes(term)) {
                        return true
                    }
                    if (session.mcp_client_name.toLowerCase().includes(term)) {
                        return true
                    }
                    return session.tools_used.some((tool) => tool.toLowerCase().includes(term))
                })
            },
        ],
        selectedSession: [
            (s) => [s.allSessions, s.selectedSessionId],
            (allSessions, selectedSessionId): MCPSessionApi | null => {
                if (!selectedSessionId) {
                    return null
                }
                return allSessions.find((session) => session.session_id === selectedSessionId) ?? null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        selectSession: ({ sessionId }) => {
            if (sessionId) {
                actions.loadToolCalls(sessionId)
            }
        },
        loadSessionsSuccess: ({ allSessions }) => {
            // Auto-select the first (most recent) session once data lands, but only
            // if the user has not already picked one — otherwise their choice would
            // be clobbered by every refresh.
            if (!values.selectedSessionId && allSessions.length > 0) {
                actions.selectSession(allSessions[0].session_id)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSessions()
    }),
])
