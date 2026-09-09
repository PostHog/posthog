import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { AttributionTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable'
import { revenueDisabledReason } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/conversionGoalFlags'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import { marketingAttributionLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAttributionLogic'
import {
    BREAKDOWN_LABELS,
    attributableConversionGoals,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'

import { MarketingAnalyticsAttributionBreakdown, NodeKind } from '~/queries/schema/schema-general'

import { marketingDashboardLogic } from './marketingDashboardLogic'

export function MarketingRevenue(): JSX.Element {
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { dateFilter, shouldFilterTestAccounts } = useValues(marketingAnalyticsLogic)
    const { revenueGoalId } = useValues(marketingDashboardLogic)
    const { setRevenueGoalId } = useActions(marketingDashboardLogic)
    const { breakdownBy } = useValues(marketingAttributionLogic)
    const { setBreakdownBy } = useActions(marketingAttributionLogic)
    const goals = attributableConversionGoals(conversion_goals).filter(
        (goal) => goal.counts_as_revenue && !revenueDisabledReason(goal)
    )
    const selectedGoal = goals.find((goal) => goal.conversion_goal_id === revenueGoalId) ?? goals[0]

    if (!selectedGoal) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Configure revenue goals',
                    to: urls.settings('environment-marketing-analytics', 'marketing-settings'),
                }}
            >
                Choose an event or action goal that sums an amount and mark it as revenue. Warehouse revenue goals are
                available in Ad performance.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-4">
                <LemonSelect
                    value={selectedGoal.conversion_goal_id}
                    onChange={(value) => value && setRevenueGoalId(value)}
                    options={goals.map((goal) => ({
                        value: goal.conversion_goal_id,
                        label: goal.conversion_goal_name,
                    }))}
                />
                <LemonSelect
                    value={breakdownBy}
                    onChange={(value) => value && setBreakdownBy(value)}
                    options={Object.values(MarketingAnalyticsAttributionBreakdown).map((value) => ({
                        value,
                        label: BREAKDOWN_LABELS[value],
                    }))}
                />
            </div>
            <p className="text-secondary mb-0">
                Revenue attributed to each touchpoint, using one goal at a time to avoid double counting. Compare models
                below. Spend and ROAS are available in Ad performance.
            </p>
            <AttributionTable
                revenue
                query={{
                    kind: NodeKind.MarketingAnalyticsAttributionQuery,
                    conversionGoalId: selectedGoal.conversion_goal_id,
                    breakdownBy,
                    dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                    filterTestAccounts: shouldFilterTestAccounts,
                    properties: [],
                    limit: 100,
                }}
            />
        </div>
    )
}
