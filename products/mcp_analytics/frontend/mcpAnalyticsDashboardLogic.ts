import { actions, afterMount, kea, listeners, path, reducers } from 'kea'

import api from 'lib/api'

interface MCPAnalyticsDashboard {
    id: number
    name: string
    description: string
}

export const mcpAnalyticsDashboardLogic = kea([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsDashboardLogic']),

    actions({
        loadMCPDashboards: true,
        loadMCPDashboardsSuccess: (availableDashboards: unknown) => ({
            availableDashboards: availableDashboards as MCPAnalyticsDashboard[],
        }),
        loadMCPDashboardsFailure: (error: unknown) => ({ error }),
    }),

    reducers({
        availableDashboards: [
            [] as MCPAnalyticsDashboard[],
            {
                loadMCPDashboardsSuccess: (_, { availableDashboards }) => availableDashboards,
            },
        ],
        availableDashboardsLoading: [
            false,
            {
                loadMCPDashboards: () => true,
                loadMCPDashboardsSuccess: () => false,
                loadMCPDashboardsFailure: () => false,
            },
        ],
        selectedDashboardId: [
            null as number | null,
            {
                loadMCPDashboardsSuccess: (state, { availableDashboards }) => {
                    if (availableDashboards.length === 0) {
                        return null
                    }

                    if (state && availableDashboards.some((dashboard: { id: number }) => dashboard.id === state)) {
                        return state
                    }

                    return availableDashboards[0].id
                },
            },
        ],
    }),

    listeners(({ actions }) => ({
        loadMCPDashboards: async () => {
            try {
                const response = await api.dashboards.list({
                    tags: 'mcp-analytics',
                    creation_mode: 'unlisted',
                })
                const dashboards = response.results || []

                actions.loadMCPDashboardsSuccess(
                    dashboards.map((dashboard) => ({
                        id: dashboard.id,
                        name: dashboard.name,
                        description: dashboard.description || '',
                    }))
                )
            } catch (error: unknown) {
                actions.loadMCPDashboardsFailure(error)
            }
        },
        loadMCPDashboardsSuccess: async ({ availableDashboards }, breakpoint) => {
            if (availableDashboards.length > 0) {
                return
            }

            try {
                await api.dashboards.createUnlistedDashboard('mcp-analytics')
                await breakpoint(100)
                actions.loadMCPDashboards()
            } catch (error: unknown) {
                const err = error as { status?: number }

                if (err.status === 409) {
                    await breakpoint(100)
                    actions.loadMCPDashboards()
                    return
                }

                console.error('Failed to create default MCP analytics dashboard:', error)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadMCPDashboards()
    }),
])
