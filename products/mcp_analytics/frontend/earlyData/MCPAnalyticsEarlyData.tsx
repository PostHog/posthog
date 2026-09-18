import { useValues } from 'kea'

import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { formatNumber } from '../dashboard/formatters'
import { METRICS_UNLOCK_LIFETIME_CALLS, mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { ActivityCallers } from './ActivityCallers'
import { ActivityFeed } from './ActivityFeed'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

/**
 * The Activity tab: answers "what are agents doing with my server?" with the
 * live feed as the hero, a one-line summary above it, and the dashboard's
 * caller charts below. It refreshes live and is the default landing tab for
 * low-volume projects, where the windowed metrics dashboard would be noise;
 * higher-volume projects land on the Dashboard tab but can always come here
 * for recency.
 */
export function MCPAnalyticsActivityDashboard(): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-activity">
            <ActivitySummary />
            <ActivityFeed />
            <ActivityCallers />
        </div>
    )
}

function ActivitySummary(): JSX.Element {
    const { dashboardStage } = useValues(mcpAnalyticsOnboardingLogic)
    const { summary, overview, overviewLoading } = useValues(mcpEarlyDataLogic)
    // The sentence is derived from the overview, and an absent overview reads as zero calls —
    // so the first load would claim "No tool calls in the last 30 days" until the numbers
    // arrive. Only the first load skeletons: the 60s refresh keeps the sentence it already has
    // rather than flashing back to a placeholder every minute.
    const awaitingFirstOverview = overviewLoading && !overview

    return (
        <div data-attr="mcp-analytics-activity-summary">
            {awaitingFirstOverview ? (
                <LemonSkeleton className="h-6 w-80 max-w-full my-1" />
            ) : (
                <h2 className="text-lg font-semibold m-0">{summary}</h2>
            )}
            <p className="text-muted m-0 mt-1">
                This view fills in live as agents use your server.
                {dashboardStage === 'activity' ? (
                    <>
                        {' '}
                        Charts and trends live in the <Link to={urls.mcpAnalyticsDashboard()}>Dashboard tab</Link>. They
                        become meaningful as usage grows (~{formatNumber(METRICS_UNLOCK_LIFETIME_CALLS)} calls).
                    </>
                ) : null}
            </p>
        </div>
    )
}
