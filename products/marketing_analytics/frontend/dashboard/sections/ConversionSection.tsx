import { useActions, useValues } from 'kea'

import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'

import { ConversionValueCards } from '../cards/ConversionValueCards'
import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { pickOverviewItems } from '../cards/metricCardSpec'
import { MetricNoticeCard } from '../cards/MetricNoticeCard'
import { WebOverviewCards } from '../cards/WebOverviewCards'
import { DashboardMetricChart } from '../charts/DashboardMetricChart'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { ConversionBreakdownTable } from '../tables/ConversionBreakdownTable'

const CONVERSION_LABELS: Record<string, string> = {
    sessions: 'Sessions',
    'total conversions': 'Conversions',
    'conversion rate': 'Conversion rate',
}

export function ConversionSection(): JSX.Element {
    const { webOverviewQuery, conversionOverviewQuery, conversionTableQuery } = useValues(marketingDashboardLogic)
    const { openSetup } = useActions(marketingAnalyticsLogic)

    const reviewGoals = (): void => openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_customer_cards')

    if (!conversionOverviewQuery || !conversionTableQuery) {
        return (
            <MarketingMetricCardGrid>
                <MetricNoticeCard
                    title="Conversions"
                    message="Pick an event or action as a conversion goal to see how each channel converts."
                    action={{
                        label: 'Set up a goal',
                        onClick: reviewGoals,
                        dataAttr: 'marketing-configure-customer-goal',
                    }}
                />
            </MarketingMetricCardGrid>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                <WebOverviewCards
                    query={webOverviewQuery}
                    dataNodeKey="marketing-dashboard-web-overview"
                    numSkeletons={1}
                    select={(results) => pickOverviewItems(results, ['sessions'])}
                    labelFromKey={(key) => CONVERSION_LABELS[key] ?? labelFromKey(key)}
                />
                <WebOverviewCards
                    query={conversionOverviewQuery}
                    dataNodeKey="marketing-dashboard-conversion-overview"
                    numSkeletons={2}
                    select={(results) => pickOverviewItems(results, ['total conversions', 'conversion rate'])}
                    labelFromKey={(key) => CONVERSION_LABELS[key] ?? labelFromKey(key)}
                />
                <ConversionValueCards />
            </MarketingMetricCardGrid>
            <DashboardMetricChart />
            <ConversionBreakdownTable query={conversionTableQuery} />
        </div>
    )
}
