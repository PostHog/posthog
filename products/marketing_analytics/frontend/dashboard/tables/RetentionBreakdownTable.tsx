import { useActions, useValues } from 'kea'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { TileId } from 'scenes/web-analytics/common'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'
import { VariationCell } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { MarketingAnalyticsRetentionQueryResponse } from '~/queries/schema/schema-general'

import { ReturnRow, pairWithPrevious, returnRate } from '../../retention/retentionSummary'
import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { BreakdownTableColumn } from './breakdownTableColumn'
import { MarketingBreakdownTable } from './MarketingBreakdownTable'

const CountCell = VariationCell({ reserveTrendSpace: false })
const RateCell = VariationCell({ isPercentage: true })
const DaysCell = VariationCell({ neutral: true, formatValue: (value) => value.toFixed(1) })

const RETENTION_COLUMNS: BreakdownTableColumn<ReturnRow>[] = [
    {
        key: 'acquired',
        title: 'New visitors',
        shortTitle: 'New',
        tooltip: 'People whose first qualifying session was in the selected date range.',
        value: (row) => [row.acquired, row.comparison?.acquired ?? null],
        Cell: CountCell,
        exportLabel: 'New visitors',
    },
    ...([7, 30] as const).map(
        (days): BreakdownTableColumn<ReturnRow> => ({
            key: `return${days}`,
            title: `${days}-day return rate`,
            shortTitle: `${days}d return`,
            tooltip: `People with a second session within ${days} days of acquisition. Only people who have had the full ${days} days count.`,
            value: (row) => {
                const rate = returnRate(row, days)
                return rate === null ? null : [rate, returnRate(row.comparison, days)]
            },
            Cell: RateCell,
            exportLabel: `${days}-day return rate`,
            exportValue: (value) => percentage(value, 1),
            tooltipContent: (row) => {
                const eligible = days === 7 ? row.eligible7d : row.eligible30d
                const returned = days === 7 ? row.returned7d : row.returned30d
                return `${humanFriendlyNumber(returned)} returned out of ${humanFriendlyNumber(eligible)} eligible.`
            },
        })
    ),
    {
        key: 'medianReturnDays',
        title: 'Median days to return',
        shortTitle: 'Days',
        tooltip: 'Median days from the first to the second session, among people seen returning within 30 days.',
        value: (row) =>
            row.medianReturnDays === null ? null : [row.medianReturnDays, row.comparison?.medianReturnDays ?? null],
        Cell: DaysCell,
        exportLabel: 'Median days to return',
        exportValue: (value) => value.toFixed(1),
    },
]

export function RetentionBreakdownTable(): JSX.Element {
    const { retentionQuery, retentionAcquisitionRange } = useValues(marketingDashboardLogic)
    const logic = dataNodeLogic({
        query: retentionQuery,
        key: 'marketing-dashboard-retention',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)

    const summary = (response as MarketingAnalyticsRetentionQueryResponse | undefined)?.summary ?? []

    return (
        <MarketingBreakdownTable
            tileId={TileId.MARKETING_RETENTION_TABLE}
            titlePrefix="Retention by"
            rows={pairWithPrevious(summary)}
            rowKey={(row) => row.breakdownValue}
            breakdownValue={(row) => row.breakdownValue}
            columns={RETENTION_COLUMNS}
            defaultSortKey="acquired"
            loading={responseLoading}
            error={!!responseError}
            onRetry={() => loadData('force_async')}
            emptyState="No new visitors in this range. Try a wider date range."
            exportFilename="marketing-retention"
            footnote={
                <>
                    Return rates count only people who have had the full window. Median days to return covers returns
                    seen within 30 days and can move as recent visitors come back.
                    {retentionAcquisitionRange.clamped
                        ? ' Retention covers the last 90 days of the selected range.'
                        : ''}
                </>
            }
        />
    )
}
