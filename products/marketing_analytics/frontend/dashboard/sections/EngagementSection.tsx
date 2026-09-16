import { useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'

import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { pickOverviewItems } from '../cards/metricCardSpec'
import { WebOverviewCards } from '../cards/WebOverviewCards'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { pagesPerSessionItem } from '../marketingDashboardMetrics'
import { WebStatsBreakdownTable } from '../tables/WebStatsBreakdownTable'
import { BOUNCE_RATE_COLUMN, PAGES_PER_SESSION_COLUMN, SESSION_DURATION_COLUMN } from '../tables/webStatsColumns'

const ENGAGEMENT_LABELS: Record<string, string> = {
    'session duration': 'Avg. session duration',
    'bounce rate': 'Bounce rate',
    pages_per_session: 'Pages per session',
}

export function EngagementSection(): JSX.Element {
    const { webOverviewQuery, engagementTableQuery } = useValues(marketingDashboardLogic)

    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                <WebOverviewCards
                    query={webOverviewQuery}
                    dataNodeKey="marketing-dashboard-web-overview"
                    numSkeletons={3}
                    select={(results) => {
                        const pagesPerSession = pagesPerSessionItem(results)
                        return [
                            ...pickOverviewItems(results, ['session duration', 'bounce rate']),
                            ...(pagesPerSession ? [pagesPerSession] : []),
                        ]
                    }}
                    labelFromKey={(key) => ENGAGEMENT_LABELS[key] ?? labelFromKey(key)}
                />
            </MarketingMetricCardGrid>
            <WebStatsBreakdownTable
                tileId={TileId.MARKETING_ENGAGEMENT_TABLE}
                titlePrefix="Engagement by"
                query={engagementTableQuery}
                dataNodeKey="marketing-dashboard-engagement-table"
                columns={[SESSION_DURATION_COLUMN, PAGES_PER_SESSION_COLUMN, BOUNCE_RATE_COLUMN]}
                defaultSortKey="session_duration"
                exportFilename="marketing-engagement"
                emptyState="No sessions in this range."
            />
        </div>
    )
}
