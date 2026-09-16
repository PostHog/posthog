import { useActions, useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'
import { MarketingAnalyticsOverviewMetric } from '~/queries/schema/schema-general'

import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { pickOverviewItems } from '../cards/metricCardSpec'
import { MetricNoticeCard } from '../cards/MetricNoticeCard'
import { RetentionCards } from '../cards/RetentionCards'
import { RevenueCard } from '../cards/RevenueCard'
import { WebOverviewCards } from '../cards/WebOverviewCards'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { WebStatsBreakdownTable } from '../tables/WebStatsBreakdownTable'
import { CONVERSION_RATE_COLUMN, SESSION_DURATION_COLUMN, VISITORS_COLUMN } from '../tables/webStatsColumns'

const OVERVIEW_LABELS: Record<string, string> = {
    visitors: 'Visitors',
    'session duration': 'Avg. session duration',
    'conversion rate': 'Conversion rate',
}

export function OverviewSection(): JSX.Element {
    const { overviewMetrics, webOverviewQuery, conversionOverviewQuery, overviewTableQuery, conversionGoal } =
        useValues(marketingDashboardLogic)
    const { setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)

    const reviewGoals = (): void => {
        setSetupSection(SetupSection.CONVERSION_GOALS)
        setActiveTab(MarketingAnalyticsTab.SETUP)
    }

    const label = (key: string): React.ReactNode => OVERVIEW_LABELS[key] ?? labelFromKey(key)

    const card = (metric: MarketingAnalyticsOverviewMetric): JSX.Element => {
        switch (metric) {
            case MarketingAnalyticsOverviewMetric.Visitors:
                return (
                    <WebOverviewCards
                        query={webOverviewQuery}
                        dataNodeKey="marketing-dashboard-web-overview"
                        numSkeletons={1}
                        select={(results) => pickOverviewItems(results, ['visitors'])}
                        labelFromKey={label}
                    />
                )
            case MarketingAnalyticsOverviewMetric.SessionDuration:
                return (
                    <WebOverviewCards
                        query={webOverviewQuery}
                        dataNodeKey="marketing-dashboard-web-overview"
                        numSkeletons={1}
                        select={(results) => pickOverviewItems(results, ['session duration'])}
                        labelFromKey={label}
                    />
                )
            case MarketingAnalyticsOverviewMetric.ReturnRate30d:
                return <RetentionCards only="return30" />
            case MarketingAnalyticsOverviewMetric.ConversionRate:
                return conversionOverviewQuery ? (
                    <WebOverviewCards
                        query={conversionOverviewQuery}
                        dataNodeKey="marketing-dashboard-conversion-overview"
                        numSkeletons={1}
                        select={(results) => pickOverviewItems(results, ['conversion rate'])}
                        labelFromKey={label}
                    />
                ) : (
                    <MetricNoticeCard
                        title="Conversion rate"
                        message="Pick an event or action as a conversion goal to track this."
                        action={{
                            label: 'Set up a goal',
                            onClick: reviewGoals,
                            dataAttr: 'marketing-configure-customer-goal',
                        }}
                    />
                )
            case MarketingAnalyticsOverviewMetric.Revenue:
                return <RevenueCard />
        }
    }

    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                {overviewMetrics.map((metric) => (
                    <div key={metric} className="contents">
                        {card(metric)}
                    </div>
                ))}
            </MarketingMetricCardGrid>
            <WebStatsBreakdownTable
                tileId={TileId.MARKETING_OVERVIEW_TABLE}
                titlePrefix="Overview by"
                query={overviewTableQuery}
                dataNodeKey="marketing-dashboard-overview-table"
                columns={[
                    VISITORS_COLUMN,
                    SESSION_DURATION_COLUMN,
                    ...(conversionGoal ? [CONVERSION_RATE_COLUMN] : []),
                ]}
                defaultSortKey="visitors"
                exportFilename="marketing-overview"
                emptyState="No traffic in this range."
            />
        </div>
    )
}
