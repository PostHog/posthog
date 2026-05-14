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

export const mcpSessionsLogic = kea<mcpSessionsLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'sessions', 'mcpSessionsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        setFilters: (filters: Partial<MCPSessionsFilters>) => ({ filters }),
        selectSession: (sessionId: string | null) => ({ sessionId }),
    }),
    loaders(({ values }) => ({
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
                        return []
                    }
                    const response = await mcpAnalyticsSessionsToolCalls(String(values.currentProjectId), sessionId)
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
