import { useActions, useValues } from 'kea'

import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { MetricNoticeCard } from './MetricNoticeCard'
import { RevenueValueCard } from './RevenueValueCard'

export function RevenueCard(): JSX.Element {
    const { revenueQuery } = useValues(marketingDashboardLogic)
    const { openSetup } = useActions(marketingAnalyticsLogic)

    if (!revenueQuery) {
        return (
            <MetricNoticeCard
                title="Revenue"
                message="Mark a conversion goal as revenue and point it at the property holding the amount."
                action={{
                    label: 'Set up revenue',
                    onClick: () => openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_revenue_banner'),
                    dataAttr: 'marketing-configure-revenue-goal',
                }}
            />
        )
    }

    return <RevenueValueCard query={revenueQuery} />
}
