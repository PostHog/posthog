import { useActions, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import {
    BREAKDOWN_LABELS,
    DASHBOARD_BREAKDOWNS,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'

import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { MarketingBreakdownTable, MarketingBreakdownTableProps } from './MarketingBreakdownTable'

type DashboardBreakdownTableProps<Row extends object> = Omit<
    MarketingBreakdownTableProps<Row>,
    'breakdownLabel' | 'titleDropdown' | 'compare' | 'currency' | 'focusedBreakdownValue' | 'onFocusBreakdown'
>

export function DashboardBreakdownTable<Row extends object>(props: DashboardBreakdownTableProps<Row>): JSX.Element {
    const { dashboardBreakdown } = useValues(marketingAnalyticsLogic)
    const { setDashboardBreakdown } = useActions(marketingAnalyticsLogic)
    const { baseCurrency } = useValues(teamLogic)
    const { breakdownLabel, compare, expandedMetric, focusedBreakdownValue } = useValues(marketingDashboardLogic)
    const { setFocusedBreakdownValue } = useActions(marketingDashboardLogic)
    return (
        <MarketingBreakdownTable
            {...props}
            breakdownLabel={breakdownLabel}
            titleDropdown={{
                value: dashboardBreakdown,
                options: DASHBOARD_BREAKDOWNS.map((value) => ({ value, label: BREAKDOWN_LABELS[value] })),
                onChange: (value) => setDashboardBreakdown(value as MarketingAnalyticsAttributionBreakdown),
            }}
            compare={compare}
            currency={baseCurrency}
            focusedBreakdownValue={focusedBreakdownValue}
            onFocusBreakdown={expandedMetric ? setFocusedBreakdownValue : undefined}
        />
    )
}
