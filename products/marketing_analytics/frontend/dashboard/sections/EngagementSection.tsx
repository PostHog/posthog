import { useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'

import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { pickOverviewItems } from '../cards/metricCardSpec'
import { WebOverviewCards } from '../cards/WebOverviewCards'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { ratioItem } from '../marketingDashboardMetrics'
import { WebStatsBreakdownTable } from '../tables/WebStatsBreakdownTable'
import {
    BOUNCE_RATE_COLUMN,
    PAGES_PER_SESSION_COLUMN,
    PAGES_PER_VISITOR_COLUMN,
    SESSIONS_PER_VISITOR_COLUMN,
    SESSION_DURATION_COLUMN,
} from '../tables/webStatsColumns'

const ENGAGEMENT_LABELS: Record<string, string> = {
    'session duration': 'Avg. session duration',
    'bounce rate': 'Bounce rate',
    pages_per_session: 'Pages per session',
    pages_per_visitor: 'Pageviews per visitor',
    sessions_per_visitor: 'Sessions per visitor',
}

export function EngagementSection(): JSX.Element {
    const { webOverviewQuery, engagementTableQuery } = useValues(marketingDashboardLogic)

    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                <WebOverviewCards
                    query={webOverviewQuery}
                    dataNodeKey="marketing-dashboard-web-overview"
                    numSkeletons={5}
                    select={(results) => [
                        ...pickOverviewItems(results, ['session duration']),
                        ...[
                            ratioItem(results, 'pages_per_session', 'views', 'sessions'),
                            ratioItem(results, 'pages_per_visitor', 'views', 'visitors'),
                            ratioItem(results, 'sessions_per_visitor', 'sessions', 'visitors'),
                        ].filter((spec) => spec !== null),
                        ...pickOverviewItems(results, ['bounce rate']),
                    ]}
                    labelFromKey={(key) => ENGAGEMENT_LABELS[key] ?? labelFromKey(key)}
                />
            </MarketingMetricCardGrid>
            <WebStatsBreakdownTable
                tileId={TileId.MARKETING_ENGAGEMENT_TABLE}
                titlePrefix="Engagement by"
                query={engagementTableQuery}
                dataNodeKey="marketing-dashboard-engagement-table"
                columns={[
                    SESSION_DURATION_COLUMN,
                    PAGES_PER_SESSION_COLUMN,
                    PAGES_PER_VISITOR_COLUMN,
                    SESSIONS_PER_VISITOR_COLUMN,
                    BOUNCE_RATE_COLUMN,
                ]}
                defaultSortKey="session_duration"
                exportFilename="marketing-engagement"
                emptyState="No sessions in this range."
            />
        </div>
    )
}
