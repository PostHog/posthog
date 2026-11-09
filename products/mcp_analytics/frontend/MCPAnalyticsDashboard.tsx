import { useValues } from 'kea'

import { MCPAnalyticsLeaderboardHome } from './leaderboardHome/MCPAnalyticsLeaderboardHome'
import { MCPAnalyticsDashboardOverview } from './MCPAnalyticsDashboardOverview'
import { mcpDashboardOverviewLogic } from './mcpDashboardOverviewLogic'

export function MCPAnalyticsDashboard(): JSX.Element {
    const { dashboardLayout } = useValues(mcpDashboardOverviewLogic)
    return dashboardLayout === 'leaderboard' ? <MCPAnalyticsLeaderboardHome /> : <MCPAnalyticsDashboardOverview />
}
