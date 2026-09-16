import { useActions, useValues } from 'kea'

import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendResult } from '~/types'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { sumTrendSeries } from '../marketingDashboardMetrics'
import { MarketingMetricCard } from './MarketingMetricCard'
import { pctChange } from './metricCardSpec'
import { MetricNoticeCard } from './MetricNoticeCard'

export function RevenueCard(): JSX.Element {
    const { revenueQuery } = useValues(marketingDashboardLogic)
    const { setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)

    if (!revenueQuery) {
        return (
            <MetricNoticeCard
                title="Revenue"
                message="Mark a conversion goal as revenue and point it at the property holding the amount."
                action={{
                    label: 'Set up revenue',
                    onClick: () => {
                        setSetupSection(SetupSection.CONVERSION_GOALS)
                        setActiveTab(MarketingAnalyticsTab.SETUP)
                    },
                    dataAttr: 'marketing-configure-revenue-goal',
                }}
            />
        )
    }

    return <RevenueValueCard />
}

function RevenueValueCard(): JSX.Element {
    const { revenueQuery } = useValues(marketingDashboardLogic)
    const logic = dataNodeLogic({
        query: revenueQuery!,
        key: 'marketing-dashboard-revenue',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading } = useValues(logic)

    const results = (response as { results?: TrendResult[] } | undefined)?.results
    const { value, previous } = sumTrendSeries(results)

    return (
        <MarketingMetricCard
            loading={responseLoading}
            labelFromKey={() => 'Revenue'}
            spec={{
                kind: 'metric',
                item: {
                    key: 'revenue',
                    kind: 'currency',
                    value,
                    previous,
                    changeFromPreviousPct: pctChange(value, previous),
                } as never,
            }}
        />
    )
}
