import { useActions, useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { WebStatsTableQuery, WebStatsTableQueryResponse } from '~/queries/schema/schema-general'

import { BreakdownTableColumn } from './breakdownTableColumn'
import { MarketingBreakdownTable } from './MarketingBreakdownTable'
import { WebStatsRow, webStatsRows } from './webStatsRows'

export interface WebStatsBreakdownTableProps {
    tileId: TileId
    titlePrefix: string
    query: WebStatsTableQuery
    dataNodeKey: string
    columns: BreakdownTableColumn<WebStatsRow>[]
    defaultSortKey: string
    exportFilename: string
    emptyState: string
    footnote?: React.ReactNode
}

export function WebStatsBreakdownTable({
    tileId,
    titlePrefix,
    query,
    dataNodeKey,
    columns,
    defaultSortKey,
    exportFilename,
    emptyState,
    footnote,
}: WebStatsBreakdownTableProps): JSX.Element {
    // Registered in the scene's collection so the header's refresh button reaches it. Deliberately
    // not attached to another logic: an attached node outlives the section and a later refresh
    // would re-run a query nobody is looking at.
    const logic = dataNodeLogic({
        query,
        key: dataNodeKey,
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)

    return (
        <MarketingBreakdownTable
            tileId={tileId}
            titlePrefix={titlePrefix}
            rows={webStatsRows(response as WebStatsTableQueryResponse | undefined)}
            rowKey={(row) => row.breakdownValue}
            breakdownValue={(row) => row.breakdownValue}
            columns={columns}
            defaultSortKey={defaultSortKey}
            loading={responseLoading}
            error={!!responseError}
            onRetry={() => loadData('force_async')}
            emptyState={emptyState}
            footnote={footnote}
            exportFilename={exportFilename}
        />
    )
}
