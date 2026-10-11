import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { MCPAnalyticsLeaderboardHome } from './leaderboardHome/MCPAnalyticsLeaderboardHome'
import { MCPAnalyticsDashboardOverview } from './MCPAnalyticsDashboardOverview'

export function MCPAnalyticsDashboard(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_LEADERBOARD_HOME] ? (
        <MCPAnalyticsLeaderboardHome />
    ) : (
        <MCPAnalyticsDashboardOverview />
    )
}
