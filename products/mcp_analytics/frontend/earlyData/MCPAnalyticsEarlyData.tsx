import { useActions, useValues } from 'kea'

import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { McpSharedFilters } from '../components/McpSharedFilters'
import { formatNumber } from '../dashboard/formatters'
import { METRICS_UNLOCK_LIFETIME_CALLS, mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { ActivityCallers } from './ActivityCallers'
import { ActivityFeed } from './ActivityFeed'
import { ActivityNextSteps } from './ActivityNextSteps'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

/**
 * The Activity tab: answers "what are agents doing with my server?" with the
 * recent feed as the hero, a one-line summary above it, the next setup step only
 * when there is one, and the dashboard's caller charts below. It loads once and
 * refreshes when filters change or the user requests it. Low-volume projects land
 * here because the windowed metrics dashboard is too sparse. Higher-volume
 * projects land on the Dashboard tab and can come here to see recent activity.
 */
export function MCPAnalyticsActivityDashboard(): JSX.Element {
    const { harnessRowsLoading, modelRowsLoading, overviewLoading } = useValues(mcpEarlyDataLogic)
    const { refreshAll } = useActions(mcpEarlyDataLogic)

    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-activity">
            <McpSharedFilters
                pageKey="mcp-activity"
                dataAttrPrefix="mcp-activity"
                onRefresh={refreshAll}
                refreshing={overviewLoading || harnessRowsLoading || modelRowsLoading}
            />
            <ActivitySummary />
            <ActivityNextSteps />
            <ActivityFeed />
            <ActivityCallers />
        </div>
    )
}

function ActivitySummary(): JSX.Element {
    const { dashboardStage } = useValues(mcpAnalyticsOnboardingLogic)
    const { summary, overview, overviewLoading } = useValues(mcpEarlyDataLogic)
    const { showFailedCallsOnly } = useActions(mcpEarlyDataLogic)
    // The sentence is derived from the overview, and an absent overview reads as zero calls —
    // so the first load would claim "No tool calls in the last 30 days" until the numbers
    // arrive. Only the first load skeletons: later refreshes keep the sentence already shown.
    const awaitingFirstOverview = overviewLoading && !overview

    // Each refreshing value sits in its own element: a bare text node next to siblings breaks under in-page translation.
    return (
        <div data-attr="mcp-analytics-activity-summary">
            {awaitingFirstOverview ? (
                <LemonSkeleton className="h-6 w-80 max-w-full my-1" />
            ) : (
                <h2 className="text-lg font-semibold m-0">
                    <span>{summary.headline}</span>
                    {summary.failures ? (
                        <>
                            <span>{summary.headline.endsWith('.') ? ' ' : '. '}</span>
                            <Link onClick={showFailedCallsOnly} data-attr="mcp-analytics-activity-failures-link">
                                <span>{summary.failures}</span> worth a look
                            </Link>
                        </>
                    ) : null}
                </h2>
            )}
            <p className="text-muted m-0 mt-1">
                This view summarizes the last 30 days of activity.
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
