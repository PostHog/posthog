import { useActions, useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { OVERVIEW_METRIC_LABELS } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'
import { MarketingAnalyticsOverviewMetric, WebOverviewQuery } from '~/queries/schema/schema-general'

import { ConversionValueCards } from '../cards/ConversionValueCards'
import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { pickOverviewItems } from '../cards/metricCardSpec'
import { MetricNoticeCard } from '../cards/MetricNoticeCard'
import { RetentionCards } from '../cards/RetentionCards'
import { RevenueCard } from '../cards/RevenueCard'
import { WebOverviewCards } from '../cards/WebOverviewCards'
import { MetricChart } from '../charts/MetricChart'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { ratioItem } from '../marketingDashboardMetrics'
import { WebStatsBreakdownTable } from '../tables/WebStatsBreakdownTable'
import { CONVERSION_RATE_COLUMN, SESSION_DURATION_COLUMN, VISITORS_COLUMN } from '../tables/webStatsColumns'

/** Cards are keyed by the result key the query returns, which is not the metric's own name. */
const OVERVIEW_LABELS: Record<string, string> = {
    visitors: 'Unique visitors',
    views: 'Pageviews',
    sessions: 'Sessions',
    'session duration': 'Avg. session duration',
    'bounce rate': 'Bounce rate',
    'total conversions': 'Conversions',
    'conversion rate': 'Conversion rate',
    pages_per_session: 'Pages per session',
    pages_per_visitor: 'Pageviews per visitor',
    sessions_per_visitor: 'Sessions per visitor',
}

const WEB_OVERVIEW_KEYS: Partial<Record<MarketingAnalyticsOverviewMetric, string>> = {
    [MarketingAnalyticsOverviewMetric.Visitors]: 'visitors',
    [MarketingAnalyticsOverviewMetric.Sessions]: 'sessions',
    [MarketingAnalyticsOverviewMetric.Pageviews]: 'views',
    [MarketingAnalyticsOverviewMetric.SessionDuration]: 'session duration',
    [MarketingAnalyticsOverviewMetric.BounceRate]: 'bounce rate',
}

/** The ratios WebOverviewQuery does not return, as [key, numerator, denominator]. */
const RATIO_KEYS: Partial<Record<MarketingAnalyticsOverviewMetric, [string, string, string]>> = {
    [MarketingAnalyticsOverviewMetric.PagesPerSession]: ['pages_per_session', 'views', 'sessions'],
    [MarketingAnalyticsOverviewMetric.PagesPerVisitor]: ['pages_per_visitor', 'views', 'visitors'],
    [MarketingAnalyticsOverviewMetric.SessionsPerVisitor]: ['sessions_per_visitor', 'sessions', 'visitors'],
}

const RETENTION_KEYS: Partial<
    Record<
        MarketingAnalyticsOverviewMetric,
        'acquired' | 'newVisitorShare' | 'returners' | 'return7' | 'return30' | 'medianReturnDays'
    >
> = {
    [MarketingAnalyticsOverviewMetric.NewVisitors]: 'acquired',
    [MarketingAnalyticsOverviewMetric.NewVisitorShare]: 'newVisitorShare',
    [MarketingAnalyticsOverviewMetric.ReturningVisitors]: 'returners',
    [MarketingAnalyticsOverviewMetric.ReturnRate7d]: 'return7',
    [MarketingAnalyticsOverviewMetric.ReturnRate30d]: 'return30',
    [MarketingAnalyticsOverviewMetric.MedianReturnDays]: 'medianReturnDays',
}

const label = (key: string): React.ReactNode => OVERVIEW_LABELS[key] ?? labelFromKey(key)

export function OverviewSection(): JSX.Element {
    const { overviewMetrics, webOverviewQuery, conversionOverviewQuery, overviewTableQuery, conversionGoal } =
        useValues(marketingDashboardLogic)
    const { setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)

    const reviewGoals = (): void => {
        setSetupSection(SetupSection.CONVERSION_GOALS)
        setActiveTab(MarketingAnalyticsTab.SETUP)
    }

    const goalCard = (metric: MarketingAnalyticsOverviewMetric, resultKey: string): JSX.Element =>
        conversionOverviewQuery ? (
            <WebOverviewCards
                query={conversionOverviewQuery}
                dataNodeKey="marketing-dashboard-conversion-overview"
                numSkeletons={1}
                select={(results) => pickOverviewItems(results, [resultKey])}
                labelFromKey={label}
            />
        ) : (
            <MetricNoticeCard
                title={OVERVIEW_METRIC_LABELS[metric]}
                message="Pick an event or action as a conversion goal to track this."
                action={{
                    label: 'Set up a goal',
                    onClick: reviewGoals,
                    dataAttr: 'marketing-configure-customer-goal',
                }}
            />
        )

    const card = (metric: MarketingAnalyticsOverviewMetric): JSX.Element => {
        const overviewKey = WEB_OVERVIEW_KEYS[metric]
        if (overviewKey) {
            return <SingleOverviewCard query={webOverviewQuery} resultKey={overviewKey} />
        }
        const ratio = RATIO_KEYS[metric]
        if (ratio) {
            return <RatioOverviewCard query={webOverviewQuery} keys={ratio} title={OVERVIEW_METRIC_LABELS[metric]} />
        }
        const retentionKey = RETENTION_KEYS[metric]
        if (retentionKey) {
            return <RetentionCards only={retentionKey} />
        }
        switch (metric) {
            case MarketingAnalyticsOverviewMetric.Conversions:
                return goalCard(metric, 'total conversions')
            case MarketingAnalyticsOverviewMetric.ConversionRate:
                return goalCard(metric, 'conversion rate')
            case MarketingAnalyticsOverviewMetric.ConversionValue:
                return <ConversionValueCards only="conversion_value" />
            case MarketingAnalyticsOverviewMetric.AvgConversionValue:
                return <ConversionValueCards only="avg_conversion_value" />
            default:
                return <RevenueCard />
        }
    }

    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                {overviewMetrics.map((metric, index) => (
                    // Keyed by slot: the same metric can be picked for two slots.
                    <div key={`${index}-${metric}`} className="contents">
                        {card(metric)}
                    </div>
                ))}
            </MarketingMetricCardGrid>
            <MetricChart />
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

function SingleOverviewCard({ query, resultKey }: { query: WebOverviewQuery; resultKey: string }): JSX.Element {
    return (
        <WebOverviewCards
            query={query}
            dataNodeKey="marketing-dashboard-web-overview"
            numSkeletons={1}
            select={(results) => pickOverviewItems(results, [resultKey])}
            labelFromKey={label}
        />
    )
}

function RatioOverviewCard({
    query,
    keys,
    title,
}: {
    query: WebOverviewQuery
    keys: [string, string, string]
    title: string
}): JSX.Element {
    const [key, numerator, denominator] = keys
    return (
        <WebOverviewCards
            query={query}
            dataNodeKey="marketing-dashboard-web-overview"
            numSkeletons={1}
            select={(results) => [
                ratioItem(results, key, numerator, denominator) ?? {
                    kind: 'notice' as const,
                    key,
                    title,
                    message: 'Not enough traffic in this range to work this out.',
                    value: 'N/A',
                },
            ]}
            labelFromKey={label}
        />
    )
}
