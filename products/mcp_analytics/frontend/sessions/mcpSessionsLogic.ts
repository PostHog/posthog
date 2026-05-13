import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { mcpAnalyticsSessionsList } from '../generated/api'
import type { MCPSessionApi } from '../generated/api.schemas'
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
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
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
    }),
    afterMount(({ actions }) => {
        actions.loadSessions()
    }),
])
