import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import {
    BREAKDOWN_LABELS,
    DASHBOARD_BREAKDOWNS,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'

/** The second way to change the breakdown. The first is the dropdown in each table's title. */
export function MarketingBreakdownSelect(): JSX.Element {
    const { dashboardBreakdown } = useValues(marketingAnalyticsLogic)
    const { setDashboardBreakdown } = useActions(marketingAnalyticsLogic)

    return (
        <LemonSelect
            size="small"
            value={dashboardBreakdown}
            onChange={(breakdown) => breakdown && setDashboardBreakdown(breakdown)}
            options={DASHBOARD_BREAKDOWNS.map((breakdown) => ({
                value: breakdown,
                label: BREAKDOWN_LABELS[breakdown],
            }))}
            renderButtonContent={(leaf) => `By ${String(leaf?.label ?? '').toLowerCase()}`}
            dropdownMatchSelectWidth={false}
            data-attr="marketing-dashboard-breakdown"
            aria-label="Breakdown"
        />
    )
}
