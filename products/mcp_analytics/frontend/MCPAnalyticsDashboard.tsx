import { useValues } from 'kea'

import { MCPAnalyticsEarlyDashboard } from './earlyData/MCPAnalyticsEarlyData'
import { MCPAnalyticsDashboardOverview } from './MCPAnalyticsDashboardOverview'
import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'

export function MCPAnalyticsDashboard(): JSX.Element {
    const { dashboardStage } = useValues(mcpAnalyticsOnboardingLogic)

    // Mature projects skip the early sections entirely — mcpEarlyDataLogic runs
    // property-reading all-time queries that are only affordable at low volume,
    // so it must not mount here once a project graduates.
    if (dashboardStage === 'mature' || dashboardStage === null) {
        return <MCPAnalyticsDashboardOverview />
    }
    return <MCPAnalyticsEarlyDashboard stage={dashboardStage} />
}
