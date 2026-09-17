import { useActions, useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'

import { ConversionValueCards } from '../cards/ConversionValueCards'
import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { pickOverviewItems } from '../cards/metricCardSpec'
import { MetricNoticeCard } from '../cards/MetricNoticeCard'
import { WebOverviewCards } from '../cards/WebOverviewCards'
import { MetricChart } from '../charts/MetricChart'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { WebStatsBreakdownTable } from '../tables/WebStatsBreakdownTable'
import { CONVERSIONS_COLUMN, CONVERSION_RATE_COLUMN, SESSIONS_COLUMN } from '../tables/webStatsColumns'

const CONVERSION_LABELS: Record<string, string> = {
    sessions: 'Sessions',
    'total conversions': 'Conversions',
    'conversion rate': 'Conversion rate',
}

export function ConversionSection(): JSX.Element {
    const { webOverviewQuery, conversionOverviewQuery, conversionTableQuery } = useValues(marketingDashboardLogic)
    const { setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)

    const reviewGoals = (): void => {
        setSetupSection(SetupSection.CONVERSION_GOALS)
        setActiveTab(MarketingAnalyticsTab.SETUP)
    }

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
            <MetricChart />
            <WebStatsBreakdownTable
                tileId={TileId.MARKETING_CONVERSION_TABLE}
                titlePrefix="Conversion by"
                query={conversionTableQuery}
                dataNodeKey="marketing-dashboard-conversion-table"
                columns={[SESSIONS_COLUMN, CONVERSIONS_COLUMN, CONVERSION_RATE_COLUMN]}
                defaultSortKey="total_conversions"
                exportFilename="marketing-conversion"
                emptyState="No conversions in this range."
                footnote="Each row counts the conversions of sessions that started on that channel. Conversion rate divides converting people by visitors."
            />
        </div>
    )
}
