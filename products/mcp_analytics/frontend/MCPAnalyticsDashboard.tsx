import { useValues } from 'kea'

import { MCPAnalyticsActivityDashboard } from './earlyData/MCPAnalyticsEarlyData'
import { MCPAnalyticsDashboardOverview } from './MCPAnalyticsDashboardOverview'
import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'

export function MCPAnalyticsDashboard(): JSX.Element {
    const { dashboardStage } = useValues(mcpAnalyticsOnboardingLogic)

    // The activity stage answers "what are agents doing?"; metrics answers "is it
    // healthy?". Metrics projects skip the activity sections entirely —
    // mcpEarlyDataLogic runs property-reading all-time queries that are only
    // affordable at low volume, so it must not mount once a project graduates.
    if (dashboardStage === 'activity') {
        return <MCPAnalyticsActivityDashboard />
    }
    return <MCPAnalyticsDashboardOverview />
}
