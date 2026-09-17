import { useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'

import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'

import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { pickOverviewItems } from '../cards/metricCardSpec'
import { RetentionCards } from '../cards/RetentionCards'
import { WebOverviewCards } from '../cards/WebOverviewCards'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { WebStatsBreakdownTable } from '../tables/WebStatsBreakdownTable'
import { SESSIONS_COLUMN, SESSIONS_PER_VISITOR_COLUMN, VIEWS_COLUMN, VISITORS_COLUMN } from '../tables/webStatsColumns'

const ACQUISITION_LABELS: Record<string, string> = {
    visitors: 'Unique visitors',
    views: 'Pageviews',
    sessions: 'Sessions',
    sessions_per_visitor: 'Sessions per visitor',
}

export function AcquisitionSection(): JSX.Element {
    const { webOverviewQuery, acquisitionTableQuery } = useValues(marketingDashboardLogic)

    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                <WebOverviewCards
                    query={webOverviewQuery}
                    dataNodeKey="marketing-dashboard-web-overview"
                    numSkeletons={2}
                    select={(results) => pickOverviewItems(results, ['visitors'])}
                    labelFromKey={(key) => ACQUISITION_LABELS[key] ?? labelFromKey(key)}
                />
                {/* New visitors and their share come from the retention summary, which is the only
                    query that knows whose first session this was. */}
                <RetentionCards only="acquired" />
                <RetentionCards only="newVisitorShare" />
                <WebOverviewCards
                    query={webOverviewQuery}
                    dataNodeKey="marketing-dashboard-web-overview"
                    numSkeletons={2}
                    select={(results) => pickOverviewItems(results, ['sessions', 'views'])}
                    labelFromKey={(key) => ACQUISITION_LABELS[key] ?? labelFromKey(key)}
                />
            </MarketingMetricCardGrid>
            <WebStatsBreakdownTable
                tileId={TileId.MARKETING_ACQUISITION_TABLE}
                titlePrefix="Acquisition by"
                query={acquisitionTableQuery}
                dataNodeKey="marketing-dashboard-acquisition-table"
                columns={[VISITORS_COLUMN, SESSIONS_COLUMN, VIEWS_COLUMN, SESSIONS_PER_VISITOR_COLUMN]}
                defaultSortKey="visitors"
                exportFilename="marketing-acquisition"
                emptyState="No traffic in this range."
            />
        </div>
    )
}
